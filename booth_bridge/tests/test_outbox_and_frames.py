"""Tests for the e-money result outbox and PASSTI frame accumulation."""

from __future__ import annotations

import json
import time

from booth_bridge.outbox import ResultOutbox
from protocols.passti.frame import STX, _lrc, is_complete_frame, trim_to_frame


def _frame(body: bytes = b"hello") -> bytes:
    payload = bytes([0x00, 0x00, 0x00, 0x00]) + body
    lh = (len(payload) >> 8) & 0xFF
    ll = len(payload) & 0xFF
    return bytes([STX, lh, ll]) + payload + bytes([_lrc(bytes([lh, ll]) + payload)])


def test_is_complete_frame_split_reads():
    full = _frame()
    assert not is_complete_frame(full[:2])
    assert not is_complete_frame(full[:-1])
    assert is_complete_frame(full)


def test_is_complete_frame_handles_leading_noise():
    assert is_complete_frame(b"\xff\x00" + _frame())
    assert trim_to_frame(b"\xff\x00" + _frame()) == _frame()


def test_is_complete_frame_no_stx():
    assert not is_complete_frame(b"garbage")
    assert not is_complete_frame(b"")


def test_outbox_put_remove_roundtrip(tmp_path):
    ob = ResultOutbox(tmp_path)
    payload = {"transaction_id": 7, "card_number": "ABC", "transaction_counter": 1, "status": "SUCCESS"}
    path = ob.put(payload)
    assert path.exists()
    assert ob.pending() == [json.loads(path.read_text())]

    ob.remove(payload)
    assert not path.exists()
    assert ob.pending() == []


def test_outbox_dedupes_same_transaction(tmp_path):
    ob = ResultOutbox(tmp_path)
    payload = {"transaction_id": 7, "card_number": "ABC", "transaction_counter": 1, "status": "SUCCESS"}
    ob.put({**payload, "balance_after": 100})
    ob.put({**payload, "balance_after": 99})
    assert len(ob.pending()) == 1


def test_outbox_drops_expired_entries(tmp_path):
    ob = ResultOutbox(tmp_path)
    path = ob.put({"transaction_id": 1, "card_number": "X", "transaction_counter": 0, "status": "SUCCESS"})
    # Backdate beyond the 24h cap.
    old = time.time() - 90000
    import os

    os.utime(path, (old, old))
    assert ob.pending() == []
    assert not path.exists()


def test_serial_read_accumulates_until_frame():
    from booth_bridge.serial_manager import SerialManager

    full = _frame()

    class _Chunked:
        """Returns the frame in two chunks, then empties."""

        def __init__(self):
            self.n = 0

        def read(self, _n: int) -> bytes:
            self.n += 1
            if self.n == 1:
                return full[:4]
            if self.n == 2:
                return full[4:]
            return b""

    out = SerialManager._read_response(_Chunked(), 5.0, is_complete_frame)
    assert out == full


def test_serial_read_times_out_before_response():
    from booth_bridge.serial_manager import SerialManager

    class _Silent:
        def read(self, _n: int) -> bytes:
            return b""

    start = time.monotonic()
    out = SerialManager._read_response(_Silent(), 0.2, is_complete_frame)
    assert out == b""
    assert time.monotonic() - start < 2.0
