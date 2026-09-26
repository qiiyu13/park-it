"""PASSTI frame builder and parser.

Implements the frame protocol from Command Protocol Reader V1.12 ENG.

Frame structure:
    STX | LEN-H | LEN-L | EF | 01 | CMD | DATA[n] | LRC
    0x02 | 0xHH  | 0xHH  |    |    |0x01-0x0C |    | XOR checksum
"""


STX = 0x02

# Command codes
CMD_INIT = 0x01
CMD_CHECK_BALANCE = 0x02
CMD_DEDUCT = 0x03
CMD_CANCEL_CORRECTION = 0x04
CMD_GET_LAST_TRANSACTION = 0x05
CMD_MIFARE = 0x07
CMD_DISPLAY_BUZZER = 0x09
CMD_DEBUG_LOG_BRI = 0x0B
CMD_GET_READER_INFO = 0x0C

# Status code mapping
STATUS_MESSAGES = {
    (0x00, 0x00, 0x00): "OK",
    (0x01, 0x10, 0x01): "General error",
    (0x01, 0x10, 0x02): "Timeout - no card detected",
    (0x01, 0x10, 0x03): "Init failed (wrong key)",
    (0x01, 0x10, 0x04): "Insufficient balance",
    (0x01, 0x10, 0x05): "Lost contact",
    (0x01, 0x10, 0x06): "Expected previous card",
    (0x01, 0x10, 0x07): "Deduct interval too short",
    (0x01, 0x10, 0x09): "BNI inactive card",
    (0x01, 0x10, 0x10): "Expected same deduct amount",
}

# Card type codes
CARD_TYPES = {
    0x01: "Luminos",
    0x02: "Mandiri eMoney",
    0x03: "BRI Brizzi",
    0x04: "BNI TapCash",
    0x05: "BCA Flazz",
    0x06: "DKI JakCard",
    0x07: "NOBU Card",
    0x08: "Mega MegaCash",
    0x09: "QR Payment",
}


def _lrc(data: bytes) -> int:
    """Calculate XOR checksum (LRC)."""
    result = 0
    for b in data:
        result ^= b
    return result


def _to_bcd(digits: str) -> bytes:
    """Convert decimal string to BCD bytes."""
    if len(digits) % 2:
        digits = "0" + digits
    return bytes(int(digits[i : i + 2], 16) for i in range(0, len(digits), 2))


def _bcd_timeout(sec: int) -> bytes:
    """Encode a timeout (0-9999 seconds) as 2-byte BCD per V1.12 §III.B.

    Examples: 10 → b"\\x00\\x10", 99 → b"\\x00\\x99", 1234 → b"\\x12\\x34".
    """
    if not 0 <= sec <= 9999:
        raise ValueError(f"Timeout must be 0..9999 seconds, got {sec}")
    return _to_bcd(f"{sec:04d}")


def is_complete_frame(raw: bytes) -> bool:
    """True when ``raw`` holds at least one full PASSTI frame.

    Used by the serial read loop to accumulate bytes across multiple reads
    instead of assuming the response arrives in one chunk within 1s.
    Scans to the first STX so leading line noise doesn't wedge the check.
    """
    start = raw.find(bytes([STX]))
    if start < 0:
        return False
    if len(raw) - start < 3:
        return False
    data_len = (raw[start + 1] << 8) | raw[start + 2]
    return len(raw) - start >= 3 + data_len + 1


def trim_to_frame(raw: bytes) -> bytes:
    """Drop leading bytes before the first STX (line noise guard)."""
    start = raw.find(bytes([STX]))
    return raw[start:] if start > 0 else raw


def build_frame(cmd: int, data: bytes = b"") -> bytes:
    """Build a PASSTI command frame.

    Args:
        cmd: Command code (0x01-0x0C)
        data: Command payload data

    Returns:
        Complete frame as bytes
    """
    payload = bytes([0xEF, 0x01, cmd]) + data
    lh = (len(payload) >> 8) & 0xFF
    ll = len(payload) & 0xFF
    chk = _lrc(bytes([lh, ll]) + payload)
    return bytes([STX, lh, ll]) + payload + bytes([chk])


def parse_response(raw: bytes) -> dict:
    """Parse a PASSTI response frame.

    Args:
        raw: Raw response bytes from reader

    Returns:
        Dict with parsed fields:
            - ok: bool (True if resp_code == 0x00 and status == 00 00 00)
            - resp_code: int (response code byte)
            - status: tuple (3 status bytes)
            - status_msg: str (human-readable status)
            - body: bytes (payload data after status)
    """
    if len(raw) < 6:
        return {"ok": False, "error": "Response too short", "raw": raw.hex()}

    if raw[0] != STX:
        return {"ok": False, "error": "Invalid STX", "raw": raw.hex()}

    data_len = (raw[1] << 8) | raw[2]
    expected_len = 3 + data_len + 1  # STX + LEN + payload + LRC

    if len(raw) < expected_len:
        return {"ok": False, "error": "Incomplete response", "raw": raw.hex()}

    payload = raw[3 : 3 + data_len]
    received_lrc = raw[3 + data_len]
    calculated_lrc = _lrc(raw[1 : 3 + data_len])

    if received_lrc != calculated_lrc:
        return {
            "ok": False,
            "error": "LRC mismatch",
            "raw": raw.hex(),
            "received_lrc": received_lrc,
            "calculated_lrc": calculated_lrc,
        }

    resp_code = payload[0]
    status = tuple(payload[1:4]) if len(payload) >= 4 else (0xFF, 0xFF, 0xFF)
    body = payload[4:] if len(payload) > 4 else b""

    ok = resp_code == 0x00 and status == (0x00, 0x00, 0x00)
    body_hex = body.hex().upper()

    return {
        "ok": ok,
        "resp_code": resp_code,
        "status": status,
        "status_msg": STATUS_MESSAGES.get(status, f"Unknown {bytes(status).hex()}"),
        "body": body,
        "body_hex": body_hex,
        "raw": raw.hex(),
    }
