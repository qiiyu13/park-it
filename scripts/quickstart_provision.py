#!/usr/bin/env python3
"""Quick Install provisioning CLI (technician one-command path).

Run by installer/_roles/server/setup.sh after services and migrations are up.
Creates/preserves the admin, site config, tariff preset, area and gate
topology, marks setup complete, and writes a 0600 hand-over summary.

Usage:
    python scripts/quickstart_provision.py
    python scripts/quickstart_provision.py --in-count 2 --out-count 2 \
        --tariff mall --site-name "Parkir ABC" --admin-password-file /tmp/pw

Never prints the admin password. Credentials go to:
    /etc/parking/install-notes.txt        (0600, human readable)
    /etc/parking/install-summary.json     (0600, for installer GUI)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.services.quickstart import provision_quickstart  # noqa: E402
from api.database import AsyncSessionLocal  # noqa: E402

NOTES_PATH = Path(
    os.environ.get("QUICKSTART_NOTES_PATH", "/etc/parking/install-notes.txt")
)
SUMMARY_PATH = Path(
    os.environ.get("QUICKSTART_SUMMARY_PATH", "/etc/parking/install-summary.json")
)
ENROLL_TOKEN_PATH = Path(
    os.environ.get("QUICKSTART_ENROLL_TOKEN_PATH", "/etc/parking/enroll-token")
)


def _server_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "localhost"


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)


def _read_password(args: argparse.Namespace) -> str | None:
    if args.admin_password_file:
        try:
            return Path(args.admin_password_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SystemExit(f"cannot read --admin-password-file: {exc}")
    env_password = os.environ.get("EPARKING_ADMIN_PASSWORD")
    return env_password.strip() if env_password else None


def _notes_text(
    result, server_ip: str, enroll_token: str | None, setup_complete: bool
) -> str:
    lines = [
        "E-Parking v2 — Quick Install Summary",
        "=" * 44,
        "",
        f"Admin URL      : http://{server_ip}/",
        f"Admin username : {result.admin_username}",
    ]
    if result.admin_created:
        lines.append(f"Admin password : {result.admin_password}")
    else:
        lines.append("Admin password : unchanged (an admin already existed)")
    lines += [
        "",
        f"Setup complete : {'yes' if setup_complete else 'no'}",
        (
            "Setup wizard   : closed (re-open only with a freshly generated token)"
            if setup_complete
            else "Setup wizard   : token kept — open http://<server>/setup?token=<token>"
        ),
        "",
        "Gates:",
    ]
    for gate in result.gates_created:
        controller = gate.get("controller") or "configure in Device (booth-driven)"
        lines.append(f"  {gate['code']:<8} {gate['direction']:<3} {controller}")
    for code in result.gates_existing:
        lines.append(f"  {code:<8} (preserved — already existed)")
    lines += ["", f"Tariff preset  : {result.tariff_preset}"]
    for item in result.tariff_items:
        lines.append(
            "  {code:<6} {name:<12} hourly={hourly:<7} cap={cap}{prog}".format(
                code=item["code"],
                name=item["name"],
                hourly=int(item.get("hourly_rate", 0)),
                cap=int(item.get("max_daily_cap", 0)),
                prog=" progressive" if item.get("is_progressive") else "",
            )
        )
    lines += ["", "Next steps:"]
    lines += [
        "  1. Log in at the Admin URL.",
        "  2. Device → Gates: set controller IP/port or serial device for each lane.",
        "  3. Device → POS/Cameras/Printers: add booth and peripherals.",
    ]
    if enroll_token:
        lines += [
            "",
            "Booth enrollment:",
            f"  Server IP : {server_ip}",
            f"  Code      : {enroll_token}",
            "  On each booth PC:",
            f"    sudo ./install.sh --booth --server-ip {server_ip} --token {enroll_token}",
        ]
    lines += ["", "=" * 44]
    return "\n".join(lines) + "\n"


async def _run(args: argparse.Namespace) -> int:
    password = _read_password(args)
    async with AsyncSessionLocal() as db:
        try:
            result = await provision_quickstart(
                db,
                admin_username=args.admin_username,
                admin_password=password,
                admin_full_name=args.admin_full_name,
                admin_email=args.admin_email,
                site_name=args.site_name,
                site_address=args.site_address,
                site_city=args.site_city,
                tariff_preset=args.tariff,
                in_count=args.in_count,
                out_count=args.out_count,
                area_name=args.area_name,
                area_code=args.area_code,
                area_capacity=args.area_capacity,
                gate_base_ip=args.gate_base_ip,
                gate_port=args.gate_port,
                complete_setup=not args.keep_setup_token,
                delete_setup_token=not args.keep_setup_token,
            )
        except ValueError as exc:
            print(f"QUICKSTART_FAILED: {exc}", file=sys.stderr)
            return 2

    server_ip = _server_ip()
    enroll_token = None
    try:
        enroll_token = ENROLL_TOKEN_PATH.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass

    _write_private(
        NOTES_PATH,
        _notes_text(
            result,
            server_ip,
            enroll_token,
            setup_complete=not args.keep_setup_token,
        ),
    )
    _write_private(SUMMARY_PATH, json.dumps(result.to_dict(), indent=2) + "\n")

    print("QUICKSTART_OK")
    print(f"Admin URL      : http://{server_ip}/")
    print(f"Admin username : {result.admin_username}")
    if result.admin_created:
        print(f"Admin password : written to {NOTES_PATH} (0600)")
    else:
        print("Admin password : unchanged (existing admin preserved)")
    print(f"Tariff preset  : {result.tariff_preset}")
    print(f"Gates created  : {len(result.gates_created)}")
    for gate in result.gates_created:
        controller = gate.get("controller") or "booth-driven / configure in Device"
        print(f"  {gate['code']} ({gate['direction']}) {controller}")
    if enroll_token:
        print(f"Booth code     : {enroll_token}")
    print(f"Hand-over notes: {NOTES_PATH}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="E-Parking v2 quick provisioning")
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--admin-full-name", default="Administrator")
    parser.add_argument("--admin-email", default=None)
    parser.add_argument("--admin-password-file", default=None)
    parser.add_argument("--site-name", default="E-Parking")
    parser.add_argument("--site-address", default=None)
    parser.add_argument("--site-city", default=None)
    parser.add_argument("--tariff", default="standard", choices=["standard", "mall"])
    parser.add_argument("--in-count", type=int, default=1)
    parser.add_argument("--out-count", type=int, default=1)
    parser.add_argument("--area-name", default="Area Utama")
    parser.add_argument("--area-code", default="MAIN")
    parser.add_argument("--area-capacity", type=int, default=100)
    parser.add_argument("--gate-base-ip", default="192.168.1.100")
    parser.add_argument("--gate-port", type=int, default=5000)
    parser.add_argument(
        "--keep-setup-token",
        action="store_true",
        help="leave setup_complete=false and keep the wizard token (advanced)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
