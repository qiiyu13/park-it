"""PASSTI bridge lifecycle: INIT, lost-contact recovery, cancel correction."""

import json
from unittest.mock import MagicMock

import pytest

from booth_bridge.serial_manager import SerialManager
from booth_bridge.websocket_server import WebSocketServer
from protocols.passti.commands import (
    cmd_cancel_correction,
    cmd_deduct,
    cmd_get_last_transaction,
    cmd_init,
)
from protocols.passti.frame import build_response

INIT_KEY = bytes.fromhex("758F40D46D95D1641448AA19B9282C05")
MID = bytes.fromhex("02034567890ABCDE")
TID = bytes.fromhex("87654321")
CARD = bytes.fromhex("5712017101900004")


def _deduct_body(
    *, amount: int = 500, remaining: int = 8700, counter: int = 1
) -> bytes:
    return (
        bytes([0x02])
        + MID
        + TID
        + bytes.fromhex("26042612000000")
        + CARD
        + amount.to_bytes(4, "big")
        + remaining.to_bytes(4, "big")
        + counter.to_bytes(4, "big")
    )


def _success(body: bytes) -> bytes:
    return build_response(0x00, b"\x00\x00\x00", body)


def _status_error(code: int) -> bytes:
    return build_response(0x00, bytes([0x01, 0x10, code]))


def _init_response() -> bytes:
    return _success(MID + TID)


def _server(side_effect: list[bytes], *, init_key: bytes | None = INIT_KEY):
    serial_manager = MagicMock(spec=SerialManager)
    serial_manager.send.side_effect = side_effect
    return WebSocketServer(
        serial_manager,
        port=0,
        api_config=None,
        emoney_init_key=init_key,
    )


async def _deduct(server: WebSocketServer, amount: int = 500) -> dict:
    return await server._process_message(
        json.dumps(
            {
                "action": "emoney_deduct",
                "amount": amount,
                "gate_id": "GOUT01",
                "gate_out_id": 1,
                "transaction_id": 42,
            }
        )
    )


class TestReaderInit:
    async def test_init_sent_before_first_deduct(self):
        server = _server([_init_response(), _success(_deduct_body())])

        result = await _deduct(server)

        assert result["status"] == "SUCCESS"
        frames = [call.args[1] for call in server.serial_manager.send.call_args_list]
        assert frames[0] == cmd_init(INIT_KEY)
        assert frames[1] == cmd_deduct(500, timeout_sec=30)
        assert server.reader_mid == MID.hex().upper()
        assert server.reader_tid == TID.hex().upper()

    async def test_init_is_not_repeated(self):
        server = _server(
            [_init_response(), _success(_deduct_body()), _success(_deduct_body())]
        )

        assert (await _deduct(server))["status"] == "SUCCESS"
        assert (await _deduct(server))["status"] == "SUCCESS"

        frames = [call.args[1] for call in server.serial_manager.send.call_args_list]
        assert frames.count(cmd_init(INIT_KEY)) == 1

    async def test_without_key_deduct_still_works(self):
        server = _server([_success(_deduct_body())], init_key=None)

        result = await _deduct(server)

        assert result["status"] == "SUCCESS"
        frames = [call.args[1] for call in server.serial_manager.send.call_args_list]
        assert frames[0] == cmd_deduct(500, timeout_sec=30)

    async def test_wrong_key_forces_reinit_on_next_attempt(self):
        server = _server(
            [
                _init_response(),
                _status_error(0x03),  # init key rejected
                _init_response(),
                _success(_deduct_body()),
            ]
        )

        assert (await _deduct(server))["status"] == "FAILED"
        assert (await _deduct(server))["status"] == "SUCCESS"

        frames = [call.args[1] for call in server.serial_manager.send.call_args_list]
        assert frames.count(cmd_init(INIT_KEY)) == 2


class TestLostContact:
    async def test_recovery_promotes_to_success(self):
        server = _server(
            [
                _init_response(),
                _status_error(0x05),
                _success(_deduct_body()),
            ]
        )

        result = await _deduct(server)

        assert result["status"] == "SUCCESS"
        assert result["recovered"] is True
        assert result["deduct_amount"] == 500
        assert result["card_number"] == CARD.hex().upper()
        frames = [call.args[1] for call in server.serial_manager.send.call_args_list]
        assert frames[2] == cmd_get_last_transaction()

    async def test_lost_contact_without_transaction_stays_lost_contact(self):
        server = _server(
            [
                _init_response(),
                _status_error(0x05),
                _success(b""),  # no last transaction
            ]
        )

        result = await _deduct(server)

        # Regression: the bridge used to downgrade this to FAILED because the
        # error body was too short to parse as a successful deduct.
        assert result["status"] == "LOST_CONTACT"
        assert result["recovered"] is False

    async def test_cancel_correction(self):
        server = _server([_success(bytes([0x02]) + CARD)])

        result = await server._process_message(
            json.dumps({"action": "emoney_cancel_correction"})
        )

        assert result["status"] == "SUCCESS"
        assert result["card_number"] == CARD.hex().upper()
        assert (
            server.serial_manager.send.call_args_list[0].args[1]
            == cmd_cancel_correction()
        )

    @pytest.mark.parametrize(
        ("code", "expected"),
        [(0x04, "INSUFFICIENT_BALANCE"), (0x06, "WRONG_CARD")],
    )
    async def test_other_error_statuses_are_preserved(self, code, expected):
        server = _server([_init_response(), _status_error(code)])

        result = await _deduct(server)

        assert result["status"] == expected
