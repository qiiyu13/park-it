"""Tests for PASSTI response parsing in booth bridge."""

import json

import pytest

from booth_bridge.websocket_server import WebSocketServer
from protocols.passti.frame import STX, _lrc


def _build_passti_frame(resp_code: int, status: tuple, body: bytes) -> bytes:
    """Build a valid PASSTI response frame."""
    payload = bytes([resp_code]) + bytes(status) + body
    lh = (len(payload) >> 8) & 0xFF
    ll = len(payload) & 0xFF
    chk = _lrc(bytes([lh, ll]) + payload)
    return bytes([STX, lh, ll]) + payload + bytes([chk])


def _make_deduct_body(
    card_type: int = 0x02,
    mid: bytes = b"\x00" * 8,
    tid: bytes = b"\x00" * 4,
    datetime_bcd: bytes = b"\x00" * 7,
    card_number: bytes = b"\x12\x34\x56\x78\x9A\xBC\xDE\xF0",
    deducted: int = 5000,
    remaining: int = 95000,
    trans_counter: int = 1,
) -> bytes:
    """Build a deduct response body."""
    return (
        bytes([card_type])
        + mid
        + tid
        + datetime_bcd
        + card_number
        + deducted.to_bytes(4, "big")
        + remaining.to_bytes(4, "big")
        + trans_counter.to_bytes(4, "big")
    )


class FakeSerialManager:
    """Fake serial manager that returns predefined responses."""

    def __init__(self, response: bytes):
        self._response = response

    def send(self, peripheral: str, data: bytes, **kwargs) -> bytes:
        return self._response


@pytest.mark.asyncio
async def test_emoney_deduct_success():
    """Test that a SUCCESS PASSTI response is parsed correctly."""
    body = _make_deduct_body(
        card_number=b"\x12\x34\x56\x78\x9A\xBC\xDE\xF0",
        deducted=5000,
        remaining=95000,
        trans_counter=42,
    )
    raw = _build_passti_frame(0x00, (0x00, 0x00, 0x00), body)
    serial_manager = FakeSerialManager(raw)
    ws = WebSocketServer(serial_manager)

    message = json.dumps({
        "action": "emoney_deduct",
        "amount": 5000,
        "gate_id": "GOUT01",
        "gate_out_id": 1,
    })
    result = await ws._process_message(message)

    assert result["action"] == "emoney_deduct_result"
    assert result["status"] == "SUCCESS"
    assert result["card_number"] == "123456789ABCDEF0"
    assert result["deduct_amount"] == 5000
    assert result["balance_before"] == 100000
    assert result["balance_after"] == 95000
    assert result["transaction_counter"] == 42
    assert result["raw_response_hex"] == raw.hex()
    assert result["gate_id"] == "GOUT01"
    assert result["gate_out_id"] == 1


@pytest.mark.asyncio
async def test_emoney_deduct_lost_contact():
    """Test that a LOST_CONTACT response returns the right status."""
    body = _make_deduct_body()
    raw = _build_passti_frame(0x00, (0x01, 0x10, 0x05), body)
    serial_manager = FakeSerialManager(raw)
    ws = WebSocketServer(serial_manager)

    message = json.dumps({
        "action": "emoney_deduct",
        "amount": 5000,
        "gate_id": "GOUT01",
        "gate_out_id": 1,
    })
    result = await ws._process_message(message)

    assert result["action"] == "emoney_deduct_result"
    assert result["status"] == "LOST_CONTACT"
    assert "raw_response_hex" in result


@pytest.mark.asyncio
async def test_emoney_deduct_insufficient_balance():
    """Test that an INSUFFICIENT_BALANCE response returns the right status."""
    body = _make_deduct_body()
    raw = _build_passti_frame(0x00, (0x01, 0x10, 0x04), body)
    serial_manager = FakeSerialManager(raw)
    ws = WebSocketServer(serial_manager)

    message = json.dumps({
        "action": "emoney_deduct",
        "amount": 5000,
    })
    result = await ws._process_message(message)

    assert result["action"] == "emoney_deduct_result"
    assert result["status"] == "INSUFFICIENT_BALANCE"


@pytest.mark.asyncio
async def test_emoney_deduct_parse_failure():
    """Test that an invalid frame returns FAILED with an error."""
    serial_manager = FakeSerialManager(b"invalid")
    ws = WebSocketServer(serial_manager)

    message = json.dumps({
        "action": "emoney_deduct",
        "amount": 5000,
    })
    result = await ws._process_message(message)

    assert result["action"] == "emoney_deduct_result"
    assert result["status"] == "FAILED"
    assert "error" in result
