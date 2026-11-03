"""Compass controller STAT response parser.

Parses controller responses to extract:
- Input states (IN1–IN4) from both STAT binary format and RSS push events
- Output states (OUT1–OUT4) from STAT binary format
- Wiegand data (W channel = RFID, X channel = UHF)

Two response formats:
  STAT polling:  STATabcdefgh  (8 binary digits, abcd=inputs, efgh=outputs)
  RSS push:      IN1ON / IN1OFF / IN2ON / ... (text events)
"""

import re


def parse_stat(response: bytes) -> dict:
    """Parse a controller response — STAT binary or RSS push event.

    Args:
        response: Raw bytes from controller

    Returns:
        Dict with extracted fields:
            - in1..in4: bool (input pin states)
            - out1..out4: bool (output/relay states, only from STAT binary)
            - wiegand_w: str | None (RFID card number, decimal)
            - wiegand_x: str | None (UHF card number, decimal)
            - raw: str (decoded raw response)
    """
    text = response.decode("latin-1", errors="ignore")

    result = {
        "in1": False,
        "in2": False,
        "in3": False,
        "in4": False,
        "out1": False,
        "out2": False,
        "out3": False,
        "out4": False,
        "wiegand_w": None,
        "wiegand_x": None,
        "raw": text,
    }

    # Format 1: STAT binary response — STATabcdefgh
    # a=in1, b=in2, c=in3, d=in4, e=out1, f=out2, g=out3, h=out4
    stat_match = re.search(r"STAT([01]{8})", text)
    if stat_match:
        bits = stat_match.group(1)
        result["in1"] = bits[0] == "1"
        result["in2"] = bits[1] == "1"
        result["in3"] = bits[2] == "1"
        result["in4"] = bits[3] == "1"
        result["out1"] = bits[4] == "1"
        result["out2"] = bits[5] == "1"
        result["out3"] = bits[6] == "1"
        result["out4"] = bits[7] == "1"
    else:
        # Short STAT form: STATxy where x=IN1, y=IN2 (LEFT-PADDED).
        # Legacy controller usage: STAT10 -> IN1 active, STAT1 -> "01" ->
        # IN2 active, STAT11 -> both. Confirmed against the legacy entry
        # prototype (IN1=ticket button, IN2=vehicle sensor).
        short_match = re.search(r"STAT([01]{1,2})(?![01])", text)
        if short_match:
            bits = short_match.group(1).zfill(2)
            result["in1"] = bits[0] == "1"
            result["in2"] = bits[1] == "1"

    # Format 2: RSS push events — IN1ON / IN1OFF / IN2ON / etc.
    # These override the STAT binary bits for the specific input.
    if "IN1ON" in text:
        result["in1"] = True
    elif "IN1OFF" in text:
        result["in1"] = False
    if "IN2ON" in text:
        result["in2"] = True
    elif "IN2OFF" in text:
        result["in2"] = False
    if "IN3ON" in text:
        result["in3"] = True
    elif "IN3OFF" in text:
        result["in3"] = False
    if "IN4ON" in text:
        result["in4"] = True
    elif "IN4OFF" in text:
        result["in4"] = False

    # Wiegand (present in both STAT and RSS responses)
    result["wiegand_w"] = _extract_wiegand(text, "W")
    result["wiegand_x"] = _extract_wiegand(text, "X")

    return result


def _extract_wiegand(text: str, channel: str) -> str | None:
    """Extract card number from Wiegand channel.

    Args:
        text: Decoded controller response
        channel: 'W' for RFID or 'X' for UHF

    Returns:
        Card number as decimal string, or None if not found
    """
    if channel not in text:
        return None

    try:
        parts = text.split(channel, 1)
        if len(parts) < 2:
            return None

        remainder = parts[1].split("\xa9", 1)[0]
        if not remainder:
            return None

        hex_chars = ""
        for ch in remainder:
            if ch in "0123456789abcdefABCDEF":
                hex_chars += ch
            else:
                break

        if not hex_chars:
            return None

        return str(int(hex_chars, 16))
    except (ValueError, IndexError):
        return None


