"""Tests for PASSTI frame protocol."""

import pytest

from protocols.passti.commands import parse_deduct_response
from protocols.passti.frame import (
    CARD_TYPES,
    STATUS_MESSAGES,
    _bcd_timeout,
    build_frame,
    build_response,
    parse_response,
)


class TestBuildFrame:
    """Test frame builder."""

    def test_frame_structure(self):
        """Frame has correct structure."""
        frame = build_frame(0x02, b"\x01\x02\x03")

        assert frame[0] == 0x02  # STX
        # LEN-H, LEN-L
        assert frame[3] == 0xEF
        assert frame[4] == 0x01
        assert frame[5] == 0x02  # CMD

    def test_empty_data(self):
        """Frame with no data."""
        frame = build_frame(0x05)

        assert frame[0] == 0x02
        assert frame[5] == 0x05  # CMD

    def test_lrc_present(self):
        """Frame ends with LRC checksum."""
        frame = build_frame(0x02, b"\x01\x02\x03")
        assert len(frame) > 6


class TestBuildResponse:
    """Responses use RESP_CODE+STATUS, not the EF 01 CMD command header."""

    def test_success_roundtrip(self):
        raw = build_response(0x00, b"\x00\x00\x00", b"\x01\x02\x03")
        parsed = parse_response(raw)
        assert parsed["ok"] is True
        assert parsed["resp_code"] == 0x00
        assert parsed["status"] == (0, 0, 0)
        assert parsed["body"] == b"\x01\x02\x03"

    def test_error_roundtrip(self):
        raw = build_response(0x00, b"\x01\x10\x05")
        parsed = parse_response(raw)
        assert parsed["ok"] is False
        assert parsed["status"] == (0x01, 0x10, 0x05)
        assert parsed["status_msg"] == "Lost contact"

    def test_status_must_be_three_bytes(self):
        with pytest.raises(ValueError):
            build_response(0x00, b"\x00\x00")


class TestParseResponse:
    """Test response parser."""

    def test_success_response(self):
        """Parse successful response."""
        # Manually construct a valid response frame
        # STX + LEN(2) + resp_code(1) + status(3) + LRC(1)
        from protocols.passti.frame import _lrc
        payload = bytes([0x00, 0x00, 0x00, 0x00])  # resp_code=00, status=00 00 00
        len_bytes = bytes([0x00, len(payload)])
        lrc = _lrc(len_bytes + payload)
        raw = bytes([0x02]) + len_bytes + payload + bytes([lrc])

        result = parse_response(raw)
        assert result["ok"] is True
        assert result["resp_code"] == 0x00
        assert result["status"] == (0x00, 0x00, 0x00)
        assert result["status_msg"] == "OK"

    def test_error_response(self):
        """Parse error response."""
        # Manually construct a valid response frame with status 01 10 04
        from protocols.passti.frame import _lrc
        payload = bytes([0x00, 0x01, 0x10, 0x04])  # resp_code=00, status=01 10 04
        len_bytes = bytes([0x00, len(payload)])
        lrc = _lrc(len_bytes + payload)
        raw = bytes([0x02]) + len_bytes + payload + bytes([lrc])

        result = parse_response(raw)
        assert result["ok"] is False
        assert result["status"] == (0x01, 0x10, 0x04)
        assert result["status_msg"] == "Insufficient balance"

    def test_too_short(self):
        """Too short response returns error."""
        result = parse_response(b"\x02\x00")
        assert result["ok"] is False
        assert "too short" in result["error"]

    def test_invalid_stx(self):
        """Invalid STX returns error."""
        result = parse_response(b"\xFF\x00\x04\xEF\x01\x00\x00\x00\x00")
        assert result["ok"] is False
        assert "STX" in result["error"]

    def test_status_messages_complete(self):
        """All status codes from V1.12 §V are mapped."""
        expected = {
            (0x00, 0x00, 0x00),
            (0x01, 0x10, 0x01),
            (0x01, 0x10, 0x02),
            (0x01, 0x10, 0x03),
            (0x01, 0x10, 0x04),
            (0x01, 0x10, 0x05),
            (0x01, 0x10, 0x06),
            (0x01, 0x10, 0x07),
            (0x01, 0x10, 0x09),  # BNI Inactive Card
            (0x01, 0x10, 0x10),  # Expected same deduct amount
        }
        for status in expected:
            assert status in STATUS_MESSAGES, f"Missing status {status}"

    def test_card_types_complete(self):
        """All expected card types are mapped."""
        expected = {
            0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09,
        }
        for card_type in expected:
            assert card_type in CARD_TYPES, f"Missing card type {card_type:02X}"


class TestBcdTimeout:
    """Test BCD timeout encoding per V1.12 §III.B."""

    @pytest.mark.parametrize(
        "sec, expected",
        [
            (0, b"\x00\x00"),
            (1, b"\x00\x01"),
            (10, b"\x00\x10"),  # V1.12 §III.B example
            (99, b"\x00\x99"),
            (100, b"\x01\x00"),
            (1234, b"\x12\x34"),
            (9999, b"\x99\x99"),
        ],
    )
    def test_bcd_timeout(self, sec, expected):
        assert _bcd_timeout(sec) == expected

    def test_bcd_timeout_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            _bcd_timeout(-1)
        with pytest.raises(ValueError):
            _bcd_timeout(10000)


class TestParseDeductResponse:
    """Test deduct response parser against V1.12 §C.1 spec examples."""

    def _make_prepaid_body(self, deducted=1, remaining=118988, counter=1):
        """Build a minimal valid prepaid card deduct response body."""
        card_type = bytes([0x01])                    # Luminos
        mid = bytes.fromhex("02034567890ABCDE")      # 8B
        tid = bytes.fromhex("87654321")              # 4B
        dt = bytes.fromhex("10122017121550")         # 7B BCD ddmmyyyyhhmmss
        card_no = bytes.fromhex("5710120620170005")  # 8B
        amt = deducted.to_bytes(4, "big")
        bal = remaining.to_bytes(4, "big")
        ctr = counter.to_bytes(4, "big")
        card_log = bytes(83)                         # placeholder log bytes
        return card_type + mid + tid + dt + card_no + amt + bal + ctr + card_log

    def test_prepaid_parse(self):
        body = self._make_prepaid_body(deducted=1, remaining=118988, counter=1)
        result = parse_deduct_response(body)
        assert result["ok"] is True
        assert result["card_type_code"] == 0x01
        assert result["card_type"] == "Luminos"
        assert result["mid"] == "02034567890ABCDE"
        assert result["tid"] == "87654321"
        assert result["card_number"] == "5710120620170005"
        assert result["deducted"] == 1
        assert result["remaining"] == 118988
        assert result["trans_counter"] == 1

    def test_prepaid_too_short(self):
        result = parse_deduct_response(bytes(39))
        assert result["ok"] is False
        assert "too short" in result["error"]

    def test_qr_parse(self):
        """V1.12 §C.1 QR Payment response body from appendix example.

        Offsets: CardType[0] MID[1:9] TID[9:13] DT[13:20] QRType[20]
                 Amt[21:25] OrderID[25:47] TrxID[47:83] RFULen[83] RFU[84:]
        """
        # From appendix: 14 Nov 2019 12:19:27, Gopay, Rp.1
        raw_hex = (
            "09"                    # card type = QR Payment          [0]
            "D019035710900001"      # MID (8B)                        [1:9]
            "57190002"              # TID (4B)                        [9:13]
            "14112019121927"        # DateTime BCD (7B)               [13:20]
            "01"                    # QR Payment Type = Gopay (1B)    [20]
            "00000001"              # Deduct Amount = Rp.1 (4B)       [21:25]
            "35333639323836393533363920191114121930303037"   # Order ID (22B) [25:47]
            "35346134623038662D363265332D343036302D386565642D383035333238656334303164"  # TrxID (36B) [47:83]
            "00"                    # RFU length = 0 (1B)             [83]
        )
        body = bytes.fromhex(raw_hex)
        assert len(body) == 84  # exactly MIN_QR_LEN
        result = parse_deduct_response(body)
        assert result["ok"] is True
        assert result["card_type_code"] == 0x09
        assert result["card_type"] == "QR Payment"
        assert result["qr_payment_type"] == 0x01
        assert result["deducted"] == 1
        assert result["card_number"] == ""
        assert result["remaining"] == 0
        assert result["trx_id"] == "54a4b08f-62e3-4060-8eed-805328ec401d"

    def test_qr_too_short(self):
        body = bytes([0x09]) + bytes(82)  # 1 + 82 = 83, need 84
        result = parse_deduct_response(body)
        assert result["ok"] is False
        assert "too short" in result["error"]

    def test_empty_body(self):
        result = parse_deduct_response(b"")
        assert result["ok"] is False
