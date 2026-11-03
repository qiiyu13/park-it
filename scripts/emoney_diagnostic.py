#!/usr/bin/env python3
"""
E-Money Reader Diagnostic Tool
==============================

Captures raw bytes from the e-money reader via controller Serial2.
Use this to debug why card taps aren't detected.

Usage:
    python scripts/emoney_diagnostic.py
"""

import os
import sys
import time

from protocols.compass.protocol import CompassTransport, cmd_qr5
from protocols.passti.commands import cmd_check_balance, cmd_init
from protocols.passti.frame import parse_response

# Site-specific values come from the environment. The controller IP and the
# reader INIT key are deployment secrets — never commit them to the repo.
CONTROLLER_IP = os.environ.get("CONTROLLER_IP", "")
CONTROLLER_PORT = int(os.environ.get("CONTROLLER_PORT", "5000"))
_key_hex = os.environ.get("EMONEY_INIT_KEY", "")
try:
    EMONEY_INIT_KEY: bytes | None = bytes.fromhex(_key_hex) if _key_hex else None
except ValueError:
    EMONEY_INIT_KEY = None


def hexdump(data: bytes, label: str = ""):
    """Print hex dump of bytes."""
    if label:
        print(f"  [{label}] {len(data)} bytes:")
    else:
        print(f"  {len(data)} bytes:")
    # Print hex
    hex_str = data.hex()
    for i in range(0, len(hex_str), 32):
        chunk = hex_str[i : i + 32]
        print(f"    {i:04x}: {chunk}")
    # Print ASCII preview
    ascii_preview = ""
    for b in data:
        if 32 <= b < 127:
            ascii_preview += chr(b)
        else:
            ascii_preview += "."
    if ascii_preview.strip("."):
        print(f"    ASCII: {ascii_preview[:60]}")


def main():
    print("╔════════════════════════════════════════════════════════════╗")
    print("║     E-MONEY READER DIAGNOSTIC                              ║")
    print("╚════════════════════════════════════════════════════════════╝")

    if not CONTROLLER_IP:
        print("❌ Set CONTROLLER_IP (and optionally CONTROLLER_PORT) in the environment.")
        sys.exit(2)
    if EMONEY_INIT_KEY is None or len(EMONEY_INIT_KEY) != 16:
        print("❌ Set EMONEY_INIT_KEY to the reader's 16-byte key (32 hex chars).")
        sys.exit(2)

    transport = CompassTransport(CONTROLLER_IP, CONTROLLER_PORT)
    try:
        transport.connect(timeout=5.0)
        print("✅ Connected to controller\n")
    except Exception as e:
        print(f"❌ Cannot connect: {e}")
        sys.exit(1)

    # Step 1: INIT
    print("=" * 60)
    print("STEP 1: Initialize reader")
    print("=" * 60)

    init_frame = cmd_init(EMONEY_INIT_KEY)
    print(f"INIT frame ({len(init_frame)} bytes):")
    hexdump(init_frame, "PASSTI")

    qr_cmd = cmd_qr5(init_frame)
    print(f"\nQR5 wrapper ({len(qr_cmd)} bytes):")
    hexdump(qr_cmd, "Compass")

    print("\nSending INIT...")
    transport.send(qr_cmd)

    # Read response with longer timeout
    transport._sock.settimeout(5.0)
    buffer = b""
    try:
        while True:
            chunk = transport._sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            print(f"  Received {len(chunk)} bytes (total: {len(buffer)})")
            # Check if we see the QT wrapper
            if b"\xa6QT" in buffer:
                break
    except TimeoutError:
        print("  (timeout)")

    print(f"\nTotal bytes received: {len(buffer)}")
    if buffer:
        hexdump(buffer, "RAW")

        # Try to extract QT data
        idx = buffer.find(b"\xa6QT")
        if idx != -1:
            # PASSTI payloads can contain 0xA9 bytes; the wrapper's footer is
            # the LAST terminator in the buffered chunk, not the first.
            footer = buffer.rfind(b"\xa9")
            if footer > idx:
                qt_data = buffer[idx + 3 : footer]
                print(f"\nExtracted QT data ({len(qt_data)} bytes):")
                hexdump(qt_data, "QT")

                result = parse_response(qt_data)
                print("\nParsed result:")
                for k, v in result.items():
                    if k == "body" and isinstance(v, bytes):
                        print(f"  {k}: {v.hex()}")
                    else:
                        print(f"  {k}: {v}")
            else:
                print("  ⚠️  Found \xa6QT but no \xa9 footer")
        else:
            print("  ⚠️  No \xa6QT found in response")
            # Try fallback
            idx = buffer.find(b"QT")
            if idx != -1:
                print(f"  Found plain 'QT' at offset {idx}")
                remainder = buffer[idx + 2 :]
                hexdump(remainder, "AFTER_QT")
    else:
        print("  ❌ No response received")

    # Step 2: Check Balance with full raw capture
    print("\n" + "=" * 60)
    print("STEP 2: Check Balance (tap card when ready)")
    print("=" * 60)
    input("  Press ENTER, then tap your e-money card within 15 seconds...")

    cb_frame = cmd_check_balance(10)  # 10 second timeout
    print(f"\nCheck Balance frame ({len(cb_frame)} bytes):")
    hexdump(cb_frame, "PASSTI")

    qr_cmd = cmd_qr5(cb_frame)
    print(f"\nQR5 wrapper ({len(qr_cmd)} bytes):")
    hexdump(qr_cmd, "Compass")

    print("\nSending Check Balance...")
    transport.send(qr_cmd)

    # Read response with very long timeout and multiple attempts
    print("\nListening for response (up to 20 seconds)...")
    transport._sock.settimeout(20.0)
    buffer = b""
    start = time.time()

    try:
        while time.time() - start < 20:
            try:
                chunk = transport._sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                print(f"  [{time.time() - start:.1f}s] Received {len(chunk)} bytes (total: {len(buffer)})")

                # Check if we have a complete response
                if b"\xa6QT" in buffer and b"\xa9" in buffer[buffer.find(b"\xa6QT"):]:
                    break
            except TimeoutError:
                print(f"  [{time.time() - start:.1f}s] (no data yet, keep listening...)")
                continue
    except KeyboardInterrupt:
        print("\n  Interrupted")

    print(f"\n{'=' * 60}")
    print("RAW RESPONSE ANALYSIS")
    print(f"{'=' * 60}")
    print(f"Total bytes received: {len(buffer)}")

    if not buffer:
        print("❌ NO RESPONSE AT ALL")
        print("\nPossible causes:")
        print("  - E-money reader not powered on")
        print("  - Serial2 cable disconnected from controller")
        print("  - Wrong baud rate on controller Serial2")
        print("  - Controller QR5 command not supported")
        transport.close()
        return

    hexdump(buffer, "FULL_RAW")

    # Try multiple extraction strategies
    print(f"\n{'=' * 60}")
    print("EXTRACTION ATTEMPTS")
    print(f"{'=' * 60}")

    # Attempt 1: Standard \xa6QT...\xa9 wrapper
    idx = buffer.find(b"\xa6QT")
    if idx != -1:
        print(f"\n[Attempt 1] Found \\xa6QT at offset {idx}")
        footer = buffer.rfind(b"\xa9")
        if footer > idx:
            qt_data = buffer[idx + 3 : footer]
            print(f"  QT data: {len(qt_data)} bytes")
            hexdump(qt_data)
            result = parse_response(qt_data)
            print("  Parse result:")
            for k, v in result.items():
                if k == "body" and isinstance(v, bytes):
                    print(f"    {k}: {v.hex()}")
                else:
                    print(f"    {k}: {v}")
        else:
            print("  No \\xa9 footer found!")

    # Attempt 2: Look for STX (0x02) directly in buffer
    stx_idx = buffer.find(b"\x02")
    if stx_idx != -1:
        print(f"\n[Attempt 2] Found STX (0x02) at offset {stx_idx}")
        potential_frame = buffer[stx_idx:]
        print(f"  Potential frame: {len(potential_frame)} bytes")
        hexdump(potential_frame[:64])
        result = parse_response(potential_frame)
        print("  Parse result:")
        for k, v in result.items():
            if k == "body" and isinstance(v, bytes):
                print(f"    {k}: {v.hex()}")
            else:
                print(f"    {k}: {v}")

    # Attempt 3: Look for EF 01 pattern (PASSTI payload start)
    ef_idx = buffer.find(b"\xef\x01")
    if ef_idx != -1:
        print(f"\n[Attempt 3] Found EF 01 at offset {ef_idx}")
        # Try to find STX before it
        search_start = max(0, ef_idx - 10)
        stx_idx2 = buffer.rfind(b"\x02", search_start, ef_idx)
        if stx_idx2 != -1:
            potential_frame = buffer[stx_idx2:ef_idx + 64]
            print(f"  Potential frame from STX: {len(potential_frame)} bytes")
            hexdump(potential_frame)
            result = parse_response(potential_frame)
            print("  Parse result:")
            for k, v in result.items():
                if k == "body" and isinstance(v, bytes):
                    print(f"    {k}: {v.hex()}")
                else:
                    print(f"    {k}: {v}")

    transport.close()
    print(f"\n{'=' * 60}")
    print("DIAGNOSTIC COMPLETE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
