"""PASSTI e-money reader diagnostic.

Usage:
    python -m scripts.hardware.passti_diagnostic /dev/ttyUSB0 9600
"""

import argparse
import sys

from protocols.passti.commands import cmd_check_balance, cmd_init
from protocols.passti.frame import CMD_GET_READER_INFO, build_frame, parse_response


def diagnose_passti(serial_port: str, baudrate: int = 38400, init_key: str = "") -> dict:
    """Run PASSTI reader diagnostic.

    Returns dict with:
    - serial_open: whether port opened
    - init: INIT command result
    - reader_info: reader info response
    - check_balance: balance check result (if card present)
    """
    results = {
        "serial_port": serial_port,
        "baudrate": baudrate,
        "serial_open": {"status": "not_tested"},
        "init": {"status": "not_tested"},
        "reader_info": {"status": "not_tested"},
        "check_balance": {"status": "not_tested"},
    }

    try:
        import serial
        ser = serial.Serial(serial_port, baudrate, timeout=2)
        results["serial_open"] = {"status": "ok"}

        # Send INIT — the protocol key is 16 raw bytes, not a 32-char string.
        if not init_key:
            results["init"] = {
                "status": "skipped",
                "error": "pass --init-key <32 hex chars>",
            }
        else:
            try:
                key = bytes.fromhex(init_key)
            except ValueError:
                key = b""
            if len(key) != 16:
                results["init"] = {
                    "status": "error",
                    "error": "init key must be 16 bytes (32 hex characters)",
                }
            else:
                init_frame = cmd_init(key)
                ser.write(init_frame)
                response = ser.read(64)
                parsed = parse_response(response)
                results["init"] = {
                    "status": "ok" if parsed.get("ok") else "failed",
                    "raw_hex": response.hex(),
                    "parsed": parsed,
                }

        # Get Reader Info
        info_frame = build_frame(CMD_GET_READER_INFO)
        ser.write(info_frame)
        response = ser.read(64)
        parsed = parse_response(response)
        results["reader_info"] = {
            "status": "ok" if parsed.get("ok") else "failed",
            "raw_hex": response.hex(),
        }

        # Check Balance (may fail if no card)
        balance_frame = cmd_check_balance(timeout_sec=5)
        ser.write(balance_frame)
        response = ser.read(64)
        parsed = parse_response(response)
        body = parsed.get("body", b"")
        has_card = len(body) >= 13
        results["check_balance"] = {
            "status": "ok" if has_card else "no_card",
            "raw_hex": response.hex(),
            "has_card": has_card,
        }

        ser.close()
    except ImportError:
        results["serial_open"] = {"status": "error", "error": "pyserial not installed"}
    except Exception as e:
        results["serial_open"] = {"status": "error", "error": str(e)}

    return results


def main():
    parser = argparse.ArgumentParser(description="PASSTI Reader Diagnostic")
    parser.add_argument("port", help="Serial port (e.g., /dev/ttyUSB0)")
    parser.add_argument("--baudrate", type=int, default=38400)
    parser.add_argument("--init-key", default="", help="16-byte init key (hex)")
    args = parser.parse_args()

    results = diagnose_passti(args.port, args.baudrate, args.init_key)
    print(results)
    sys.exit(0 if results["serial_open"]["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
