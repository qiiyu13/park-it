"""Critical print worker jobs.

Supports three print modes per gate:
- CONTROLLER_PASSTHROUGH: ESC/POS via controller socket (Compass \xa6PR3/\xa6PR4 or ENET :PR4)
- NETWORK: python-escpos Network printer (TCP/IP)
- SERIAL: python-escpos Serial printer (RS-232)
"""

from __future__ import annotations

from typing import Any

from arq import Retry

from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("print_worker")


def _probe_network_printer(ip: str | None, port: int | None = 9100, timeout: float = 1.0) -> bool:
    """True when something accepts TCP on the printer's raw port."""
    if not ip:
        return False
    import socket

    try:
        with socket.create_connection((ip, int(port or 9100)), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_usb_printer(device: str | None) -> bool:
    """True when a usblp character device (e.g. /dev/usb/lp1) exists."""
    if not device:
        return False
    import os

    return os.path.exists(device)


def _probe_serial_device(device: str | None) -> bool:
    if not device:
        return False
    # usblp character devices (/dev/usb/lp*) are printers, not serial ports —
    # they are handled by the USB writer, not python-escpos Serial.
    if str(device).startswith("/dev/usb/lp"):
        return False
    import os

    try:
        return os.path.exists(os.path.realpath(device))
    except OSError:
        return False


async def _retry_or_alert(ctx: dict[str, Any], gate_id: str, kind: str, error: str) -> dict[str, str]:
    """Retry the print job, or on the final attempt raise an operator alert.

    ARQ caps attempts at ``max_tries``. Re-raising ``Retry`` on the last attempt
    would let the job die silently — the operator never learns the ticket/receipt
    didn't come out. On the final try we instead publish a ``print_failed_alert``
    event (POS listens) so the operator can reprint manually, and return a failed
    result so the job ends cleanly.
    """
    job_try = ctx.get("job_try", 1)
    max_tries = ctx.get("max_tries", 3)
    if job_try < max_tries:
        raise Retry(defer=job_try * 5)

    logger.error("print_giving_up", gate_id=gate_id, kind=kind, error=error, job_try=job_try)
    redis = ctx.get("redis")
    if redis is not None:
        import json

        try:
            await redis.publish(
                f"parking.events.{gate_id}",
                json.dumps({
                    "event_type": "print_failed_alert",
                    "gate_id": gate_id,
                    "kind": kind,
                    "error": error,
                }),
            )
        except Exception as e:
            logger.error("print_alert_publish_failed", gate_id=gate_id, error=str(e))
    return {"status": "failed", "message": f"{kind} print failed after {max_tries} attempts", "error": error}


def _mock_write(gate_id: str, kind: str, escpos_data: bytes) -> str:
    """Write ESC/POS bytes + decoded text to MOCK_HARDWARE_DIR/print/. Returns path."""
    from datetime import datetime
    from pathlib import Path

    settings = get_settings()
    base = Path(settings.mock_hardware_dir) / "print"
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    stem = base / f"{gate_id}_{kind}_{ts}"
    stem.with_suffix(".bin").write_bytes(escpos_data)
    decoded = escpos_data.decode("latin-1", errors="replace")
    stem.with_suffix(".txt").write_text(decoded)
    return str(stem)


# ---------------------------------------------------------------------------
# Paper Counter Helpers
# ---------------------------------------------------------------------------

async def _check_paper_available(gate_id: str) -> tuple[bool, int | None]:
    """Check if paper is available for the given gate.

    Returns:
        (can_print, printer_id) — can_print is False when paper counter
        is enabled and remaining count is 0.
    """
    settings = get_settings()
    if not settings.printer_paper_counter_enabled:
        return True, None

    try:
        from sqlalchemy import select

        from api.app.models.printer import Printer
        from api.database import AsyncSessionLocal as async_session_factory  # noqa: N813

        async with async_session_factory() as db:
            result = await db.execute(
                select(Printer).where(
                    Printer.gate_id == gate_id,
                    Printer.is_active == True,  # noqa: E712
                ).order_by(Printer.id)
            )
            printer = result.scalars().first()
            if printer is None:
                logger.warning("no_printer_found", gate_id=gate_id)
                return True, None  # No printer record = no tracking

            if printer.paper_remaining <= 0:
                logger.warning(
                    "paper_empty_skip_print",
                    gate_id=gate_id,
                    printer_id=printer.id,
                )
                return False, printer.id

            return True, printer.id
    except Exception as e:
        logger.error("paper_check_failed", gate_id=gate_id, error=str(e))
        return True, None  # Fail open: allow print if check fails


async def _decrement_paper_counter(printer_id: int) -> None:
    """Decrement paper counter after a successful print."""
    settings = get_settings()
    if not settings.printer_paper_counter_enabled or printer_id is None:
        return

    try:
        from api.app.models.printer import Printer
        from api.database import AsyncSessionLocal as async_session_factory  # noqa: N813

        async with async_session_factory() as db:
            from sqlalchemy import select

            result = await db.execute(
                select(Printer).where(Printer.id == printer_id)
            )
            printer = result.scalar_one_or_none()
            if printer and printer.paper_remaining > 0:
                printer.paper_remaining -= 1
                await db.commit()

                # Check thresholds
                if printer.paper_remaining <= settings.printer_paper_critical_threshold:
                    logger.warning(
                        "paper_critical",
                        printer_id=printer_id,
                        remaining=printer.paper_remaining,
                    )
                elif printer.paper_remaining <= settings.printer_paper_warning_threshold:
                    logger.warning(
                        "paper_warning",
                        printer_id=printer_id,
                        remaining=printer.paper_remaining,
                    )
    except Exception as e:
        logger.error("paper_decrement_failed", printer_id=printer_id, error=str(e))


async def _get_site_header() -> tuple[str, str]:
    """(site name, subtitle) for ticket/receipt headers (cached 60s).

    Subtitle = city/address from SiteConfig, like the reference receipt's
    "PASAR PAGI KALIWUNGU" / "KALIWUNGU" pair.
    """
    global _SITE_NAME_CACHE
    now = __import__("time").monotonic()
    if _SITE_NAME_CACHE and now - _SITE_NAME_CACHE[1] < 60:
        return _SITE_NAME_CACHE[0]
    try:
        from sqlalchemy import select

        from api.app.models.site_config import SiteConfig
        from api.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(SiteConfig).limit(1))
            cfg = result.scalar_one_or_none()
            name = (cfg.name if cfg and cfg.name else "") or ""
            subtitle = (
                (cfg.city if cfg and cfg.city else "") or (cfg.address if cfg and cfg.address else "")
            ) or ""
        _SITE_NAME_CACHE = ((name, subtitle), now)
        return _SITE_NAME_CACHE[0]
    except Exception as exc:  # never break printing over a header lookup
        logger.warning("site_name_lookup_failed", error=str(exc))
        return _SITE_NAME_CACHE[0] if _SITE_NAME_CACHE else ("", "")


async def _get_site_name() -> str:
    """Site name for the ticket header/footer (cached 60s)."""
    return (await _get_site_header())[0]


_SITE_NAME_CACHE: tuple[str, float] | None = None

def _split_ticket_datetime(timestamp: str) -> tuple[str, str]:
    """Return (dd-Mon-yyyy, HH:MM:SS) from an ISO-ish string, else now."""
    from datetime import datetime

    dt = None
    if timestamp:
        for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(timestamp[: len(fmt) + 4], fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(timestamp)
            except ValueError:
                dt = None
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%d-%b-%Y"), dt.strftime("%H:%M:%S")


# This clone prints 48 columns across the paper, measured from the photos of its
# own receipts (a 42-col layout sat ~3 columns left of centre); 32 wrapped.
PAPER_COLS_58MM = 48

# Spaces in front of GATE/TANGGAL/JAM on the USB ticket. The block is printed
# left-aligned; this shifts it right so it doesn't hug the paper edge.
TICKET_BLOCK_INDENT = 4


def _center_double_width(text: str, cols: int = PAPER_COLS_58MM) -> bytes:
    """Centre a double-width line (each glyph takes two columns)."""
    body = text[: cols // 2]
    pad = max(0, (cols - 2 * len(body)) // 2)
    return (" " * pad + body + "\n").encode()


def _center_line(text: str, cols: int = PAPER_COLS_58MM) -> bytes:
    """Centre a line by padding spaces.

    Deliberately avoids ESC a: some USB/POS clones ignore the alignment
    command and print the "a" as a stray character ("aTIKET PARKIR").
    """
    text = text[:cols]
    pad = max(0, (cols - len(text)) // 2)
    return (" " * pad + text + "\n").encode()


def _build_escpos_ticket(
    barcode: str,
    gate_name: str = "",
    location_name: str = "",
    additional_info: str = "",
    timestamp: str = "",
) -> bytes:
    """Entry ticket for a 58 mm clone printer.

    Root cause of the off-centre prints: this unit keeps printer state between
    jobs (no ESC @ reset — ESC commands are printed literally), so a previous
    left margin / print-width / alignment setting leaked into later tickets.

    We therefore set the geometry explicitly on every job and centre by spaces
    inside a known 32-column line:
        GS L 0 0    left margin = 0
        GS W 128 1  print width = 384 dots (58 mm)
        GS a 0      left alignment (no stray-char risk)
    """
    date_str, time_str = _split_ticket_datetime(timestamp)
    site = location_name or ""
    gs = b"\x1d"

    def line(text: str) -> bytes:
        return (text + "\n").encode()

    def center(text: str) -> bytes:
        body = text[:32]
        return line(" " * max(0, (32 - len(body)) // 2) + body)

    lines = [
        center("TIKET PARKIR"),
        b"\x1b!\x10",                        # ESC ! double height (old working code)
        center(site),
        b"\x1b!\x00",                        # normal size
        line(""),
        line(f"GATE    : {gate_name}"),
        line(f"TANGGAL : {date_str}"),
        line(f"JAM     : {time_str}"),
        line(""),
        b" " * 2,                              # small barcode indent
        gs + b"h\x64",                       # barcode height
        gs + b"H\x02",                       # human-readable below
        gs + b"k\x45",                       # CODE39
        bytes([len(barcode)]) + barcode.encode(),  # format B: no terminator
        b"\n\n",
        center("JANGAN TINGGALKAN BARANG BAWAAN ANDA"),
        center(f"-{site}-"),
        (line(additional_info) if additional_info else b""),
        b"\n\n\n",
        gs + b"V\x00",                       # full cut
    ]
    return b"".join(lines)


PAPER_COLS = PAPER_COLS_58MM  # exit receipt prints on the same 58 mm stock as gate-in

_STRUK_LABEL_PAD = 15  # value column: "WAKTU KELUAR : " then the value
_STRUK_INDENT = 2  # label block sits a little in from the paper edge


def _format_rp(fee: Any) -> str:
    """Photo format: Rp. 2.000,- (dot thousands, ,- tail)."""
    try:
        return "Rp. " + f"{int(fee or 0):,}".replace(",", ".") + ",-"
    except (TypeError, ValueError):
        return f"Rp. {fee},-"


def _format_dt(iso: str) -> str:
    """ISO datetime → dd-Mon-yyyy / HH:MM:SS parts for the wrapped label lines."""
    if not iso:
        return "", ""
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d-%b-%Y"), dt.strftime("%H:%M:%S")
    except ValueError:
        parts = (iso[:10], iso[11:19])
        return parts


def _format_duration(entry_iso: str, exit_iso: str, existing: str) -> str:
    """Indonesian days/hours/minutes, e.g. "1 Hari 2 Jam 5 Menit".

    Leading zero units are dropped ("2 Jam 5 Menit", "5 Menit"); minutes always
    show, so a stay under a minute reads "0 Menit". Seconds are not printed.
    """
    if existing:
        return existing
    if not entry_iso or not exit_iso:
        return ""
    try:
        from datetime import datetime

        delta = datetime.fromisoformat(exit_iso) - datetime.fromisoformat(entry_iso)
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return ""
        minutes_total = seconds // 60
        d, rem = divmod(minutes_total, 24 * 60)
        h, m = divmod(rem, 60)
        parts = []
        if d:
            parts.append(f"{d} Hari")
        if d or h:
            parts.append(f"{h} Jam")
        parts.append(f"{m} Menit")
        return " ".join(parts)
    except ValueError:
        return ""


def _build_escpos_receipt(
    transaction_data: dict[str, Any],
    location_name: str = "",
) -> bytes:
    """Build ESC/POS exit receipt matching the PASAR PAGI KALIWUNGU reference:
    centred header block (STRUK PARKIR / big site name / subtitle), fee line,
    vehicle/gate line, then a left-aligned WAKTU MASUK/KELUAR, DURASI, PETUGAS
    block and the thank-you footer.

    Accepts both the producer's keys (fee, entry_time, exit_time — what
    payment.py actually enqueues) and the legacy display keys (total_fee,
    time_in, ...). Only accepting the legacy set printed every receipt with
    blank TOTAL and dates.

    42-column stock: the site name is double-width (21 cols/line max, same
    chunking as the gate-in ticket); "date time" fits on one line.
    """
    fee = transaction_data.get("total_fee")
    if fee is None:
        fee = transaction_data.get("fee", 0)
    entry_iso = transaction_data.get("entry_time") or ""
    exit_iso = transaction_data.get("exit_time") or ""

    time_in = transaction_data.get("time_in") or _format_dt(entry_iso)[1]
    time_out = transaction_data.get("time_out") or _format_dt(exit_iso)[1]
    date_in = _format_dt(entry_iso)[0]
    date_out = _format_dt(exit_iso)[0]

    duration = _format_duration(entry_iso, exit_iso, transaction_data.get("duration", ""))

    gate_name = (transaction_data.get("gate_name") or "").strip()
    vehicle_type = (transaction_data.get("vehicle_type") or "").strip()
    operator = transaction_data.get("operator_name") or ""

    # "Mobil - Keluar Mobil" / "Motor - Keluar Motor": vehicle type, then gate name.
    veh_gate = " - ".join(p for p in (vehicle_type, gate_name) if p)

    cols = PAPER_COLS

    def line(text: str) -> bytes:
        return (text[:cols] + "\n").encode()

    def center(text: str) -> bytes:
        text = text[:cols]
        pad = max(0, (cols - len(text)) // 2)
        return line(" " * pad + text)

    def label_row(label: str, value: str) -> bytes:
        """Left block "WAKTU KELUAR: value"; long values wrap at the last
        space (date / time on separate lines). Empty value = skip the row."""
        if not value:
            return b""
        key = " " * _STRUK_INDENT + f"{label[:_STRUK_LABEL_PAD - 2]:<{_STRUK_LABEL_PAD - 2}}: "
        room = cols - _STRUK_LABEL_PAD - _STRUK_INDENT
        if len(value) <= room:
            return line(f"{key}{value}")
        split = value.rfind(" ", 0, room)
        head, tail = (value[:split], value[split + 1:]) if split > 0 else (value[:room], value[room:])
        out = [line(f"{key}{head}")]
        out.append(line(" " * (_STRUK_LABEL_PAD + _STRUK_INDENT) + tail))
        return b"".join(out)

    # Raw double-width+height for the site name: ESC ! 0x30. Centered by spaces
    # inside the double-width line (16 cols) — clone printers ignore ESC a.
    # Chunks break at spaces so "SWALAYAN ADA WELERI" wraps as
    # "SWALAYAN ADA"/"WELERI", never mid-word.
    site = location_name or ""
    site_lines = []
    chunk_len = cols // 2
    start = 0
    while start < len(site):
        body = site[start:start + chunk_len]
        if start + chunk_len < len(site) and " " in body:
            split = body.rfind(" ")
            body, start = body[:split], start + split + 1
        else:
            start += chunk_len
        body = body.strip()
        if body:
            pad = max(0, (chunk_len - len(body)) // 2)
            site_lines.append(line(" " * pad + body))
    subtitle = (transaction_data.get("site_subtitle") or "").strip()

    lines: list[bytes] = [
        b"\x1b@\x1b@\x1b@\x1b@\x1b@",  # full init ×5 — kill any leaked state
        center("STRUK PARKIR"),
        b"\x1b!\x30",  # double width + height
        b"".join(site_lines),
        b"\x1b!\x00",
    ]
    if subtitle:
        lines.append(center(subtitle))
    # Fare: bold + double height only (ESC E 1 + ESC ! 0x10). Width stays normal,
    # so the line centres like the other text; double width ran off to the right.
    lines += [
        line(""),
        b"\x1bE\x01\x1b!\x10",
        center(_format_rp(fee)),
        b"\x1b!\x00\x1bE\x00",
        line(""),  # same gap below as above, so the fare sits between title and gate
    ]
    if veh_gate:
        lines.append(center(veh_gate))
    lines += [
        line(""),
        label_row("WAKTU MASUK", f"{date_in} {time_in}".strip()),
        label_row("WAKTU KELUAR", f"{date_out} {time_out}".strip()),
        label_row("DURASI", duration),
        label_row("PETUGAS", operator),
        line(""),
        center("TERIMAKASIH ATAS KUNJUNGAN ANDA"),
        # 2 blank lines past the tear bar, then V1's cut variant
        # (GS V 65 0) — this printer ignores plain GS V 0.
        b"\n\n\n" + b"\x1d\x56\x41\x00",
    ]
    return b"".join(lines)


async def _get_print_config(gate_id: str, gate_type: str = "OUT") -> dict[str, Any]:
    """Resolve printer connection config from DB for the given gate.

    Returns a print_config dict ready for _print_via_* functions.
    Falls back to CONTROLLER_PASSTHROUGH using the gate's own controller details.
    """
    try:
        from sqlalchemy import select

        from api.app.models.gate import Gate
        from api.app.models.printer import Printer
        from api.database import AsyncSessionLocal as async_session_factory  # noqa: N813

        async with async_session_factory() as db:
            printer_result = await db.execute(
                select(Printer).where(
                    Printer.gate_id == gate_id,
                    Printer.gate_type == gate_type,
                    Printer.is_active == True,  # noqa: E712
                ).order_by(Printer.id)
            )
            # A gate may have several printers; the oldest wins, as in daemons/cli.py.
            printer = printer_result.scalars().first()

            gate_result = await db.execute(select(Gate).where(Gate.code == gate_id))
            gate = gate_result.scalar_one_or_none()

            # Shared device references: gate hardware_config.printer_id (set
            # from the gate form) wins over a printer row bound to the gate,
            # so one physical printer can serve several gates.
            if gate is not None:
                pid = (gate.hardware_config or {}).get("printer_id")
                if pid:
                    try:
                        shared = await db.get(Printer, int(pid))
                    except (TypeError, ValueError):
                        shared = None
                    if shared is not None:
                        printer = shared

            # Booth-driven exits: the booth may point at a shared printer too.
            if printer is None and gate is not None and gate_type == "OUT":
                from api.app.models.pos import Pos

                pos = await db.get(Pos, gate.pos_id) if gate.pos_id else None
                pid = (pos.booth_peripherals or {}).get("printer_id") if pos else None
                if pid:
                    try:
                        shared = await db.get(Printer, int(pid))
                    except (TypeError, ValueError):
                        shared = None
                    if shared is not None:
                        printer = shared

            if printer is None or printer.mode in ("CONTROLLER_PASSTHROUGH", "AUTO"):
                # AUTO: use the first transport that actually answers right now,
                # so swapping a printer (network ↔ serial ↔ behind-controller)
                # needs no settings change.
                if printer is not None and (
                    _probe_network_printer(printer.ip_address, printer.port)
                ):
                    return {
                        "mode": "NETWORK",
                        "printer_ip_address": printer.ip_address,
                        "printer_port": printer.port or 9100,
                    }
                if printer is not None and _probe_serial_device(printer.serial_device):
                    return {
                        "mode": "SERIAL",
                        "printer_device": printer.serial_device,
                        "baudrate": printer.baudrate,
                    }
                if printer is not None and _probe_usb_printer(printer.serial_device):
                    return {"mode": "USB", "printer_device": printer.serial_device}
                # Fall back to controller passthrough using gate connection details
                cfg: dict[str, Any] = {"mode": "CONTROLLER_PASSTHROUGH"}
                if gate:
                    cfg["protocol"] = gate.protocol
                    cfg["controller_host"] = gate.controller_host
                    cfg["controller_port"] = gate.controller_port
                return cfg

            if printer.mode == "NETWORK":
                return {
                    "mode": "NETWORK",
                    "printer_ip_address": printer.ip_address,
                    "printer_port": printer.port or 9100,
                }

            if printer.mode == "SERIAL":
                return {
                    "mode": "SERIAL",
                    "printer_device": printer.serial_device,
                    "baudrate": printer.baudrate,
                }

            if printer.mode == "USB":
                return {"mode": "USB", "printer_device": printer.serial_device}

            return {"mode": printer.mode}

    except Exception as e:
        logger.error("get_print_config_failed", gate_id=gate_id, error=str(e))
        return {"mode": "CONTROLLER_PASSTHROUGH"}


async def print_ticket(
    ctx: dict[str, Any],
    gate_id: str,
    barcode: str,
    gate_name: str = "",
    location_name: str = "",
    additional_info: str = "",
    timestamp: str = "",
    print_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Print an entry ticket.

    Args:
        gate_id: Gate identifier
        barcode: Barcode content (CODE39)
        gate_name: Display name of the gate
        location_name: Parking location name
        additional_info: Footer text on ticket
        timestamp: Entry timestamp string
        print_config: Dict with printer configuration:
            - mode: "CONTROLLER_PASSTHROUGH" | "NETWORK" | "SERIAL"
            - protocol: "compass" | "enet" (for passthrough mode)
            - controller_host, controller_port (for passthrough)
            - printer_ip_address, printer_port (for network)
            - printer_device, baudrate (for serial)
    """
    if not print_config:
        print_config = await _get_print_config(gate_id, gate_type="IN")
    mode = print_config.get("mode", "CONTROLLER_PASSTHROUGH")

    # Paper counter check
    can_print, printer_id = await _check_paper_available(gate_id)
    if not can_print:
        return {
            "status": "skipped",
            "message": "Paper empty — display barcode on LED instead",
            "barcode": barcode,
        }

    logger.info(
        "print_ticket_job",
        gate_id=gate_id,
        barcode=barcode,
        mode=mode,
    )

    if not location_name:
        location_name = await _get_site_name()
    escpos_data = _build_escpos_ticket(
        barcode=barcode,
        gate_name=gate_name,
        location_name=location_name,
        additional_info=additional_info,
        timestamp=timestamp,
    )

    if get_settings().mock_hardware:
        path = _mock_write(gate_id, "ticket", escpos_data)
        logger.info("mock_ticket_written", gate_id=gate_id, path=path)
        await _decrement_paper_counter(printer_id)
        return {"status": "success", "message": "Ticket printed (MOCK)", "path": path}

    try:
        if mode == "USB":
            if not location_name:
                location_name = await _get_site_name()
            _print_ticket_via_usb_printer(
                device=print_config.get("printer_device") or "/dev/usb/lp0",
                barcode=barcode,
                gate_name=gate_name,
                site_name=location_name,
                timestamp=timestamp,
                additional_info=additional_info,
            )
        elif mode == "NETWORK":
            if not location_name:
                location_name = await _get_site_name()
            _print_ticket_via_network_printer(
                host=print_config.get("printer_ip_address") or "",
                port=print_config.get("printer_port") or 9100,
                barcode=barcode,
                gate_name=gate_name,
                site_name=location_name,
                timestamp=timestamp,
                additional_info=additional_info,
            )
        elif mode == "CONTROLLER_PASSTHROUGH":
            # The entry gate daemon owns this single-client controller and prints
            # passthrough tickets itself (PR3). A second socket from here would be
            # refused or steal its slot. Fail into retry/alert, never connect.
            raise RuntimeError(
                "entry controller is owned by the gate daemon; worker will not open it"
            )
        elif mode == "SERIAL":
            _print_via_serial(escpos_data, print_config)
        else:
            raise ValueError(f"Unknown print mode: {mode}")

        # Decrement paper counter on success
        await _decrement_paper_counter(printer_id)

        from api.app.middleware.metrics import print_jobs_total
        print_jobs_total.labels(kind="ticket", result="success").inc()
        return {"status": "success", "message": "Ticket printed"}
    except Exception as e:
        logger.error("print_ticket_failed", gate_id=gate_id, error=str(e))
        from api.app.middleware.metrics import print_jobs_total
        print_jobs_total.labels(kind="ticket", result="failure").inc()
        return await _retry_or_alert(ctx, gate_id, "ticket", str(e))


async def print_receipt(
    ctx: dict[str, Any],
    gate_id: str,
    transaction_data: dict[str, Any],
    location_name: str = "",
    print_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Print an exit receipt.

    Args:
        gate_id: Gate identifier
        transaction_data: Transaction details dict
        location_name: Parking location name
        print_config: Same format as print_ticket
    """
    if not print_config:
        print_config = await _get_print_config(gate_id, gate_type="OUT")
    mode = print_config.get("mode", "CONTROLLER_PASSTHROUGH")

    # Paper counter check
    can_print, printer_id = await _check_paper_available(gate_id)
    if not can_print:
        return {
            "status": "skipped",
            "message": "Paper empty — receipt not printed",
        }

    logger.info(
        "print_receipt_job",
        gate_id=gate_id,
        transaction_id=transaction_data.get("id"),
        mode=mode,
    )

    if not location_name:
        location_name, site_subtitle = await _get_site_header()
        transaction_data.setdefault("site_subtitle", site_subtitle)

    escpos_data = _build_escpos_receipt(
        transaction_data=transaction_data,
        location_name=location_name,
    )

    if get_settings().mock_hardware:
        path = _mock_write(gate_id, "receipt", escpos_data)
        logger.info("mock_receipt_written", gate_id=gate_id, path=path)
        await _decrement_paper_counter(printer_id)
        return {"status": "success", "message": "Receipt printed (MOCK)", "path": path}

    try:
        if mode == "CONTROLLER_PASSTHROUGH":
            _print_via_controller(escpos_data, print_config)
        elif mode == "NETWORK":
            _print_via_network(escpos_data, print_config)
        elif mode == "SERIAL":
            _print_via_serial(escpos_data, print_config)
        elif mode == "USB":
            _print_via_usb(escpos_data, print_config)
        else:
            raise ValueError(f"Unknown print mode: {mode}")

        # Decrement paper counter on success
        await _decrement_paper_counter(printer_id)

        from api.app.middleware.metrics import print_jobs_total
        print_jobs_total.labels(kind="receipt", result="success").inc()
        return {"status": "success", "message": "Receipt printed"}
    except Exception as e:
        logger.error("print_receipt_failed", gate_id=gate_id, error=str(e))
        from api.app.middleware.metrics import print_jobs_total
        print_jobs_total.labels(kind="receipt", result="failure").inc()
        return await _retry_or_alert(ctx, gate_id, "receipt", str(e))


def _print_via_controller(escpos_data: bytes, config: dict[str, Any]) -> None:
    """Send ESC/POS data through controller passthrough."""
    protocol = config.get("protocol", "compass")
    host = config["controller_host"]
    port = config["controller_port"]

    if protocol == "compass":
        # Compass passthrough is PR3 (Serial1 @ 9600) — same command the gate-in
        # daemon prints tickets with. PR4 is ENET-only; importing it here raised
        # ImportError and silently dead-lettered every passthrough print job.
        from protocols.compass.protocol import CompassTransport
        from protocols.compass.protocol import cmd_pr3 as cmd_print
        transport = CompassTransport(host, port)

    elif protocol == "enet":
        from protocols.compass.protocol import CompassTransport as EnetTransport
        from protocols.enet.protocol import cmd_pr4 as cmd_print
        transport = EnetTransport(host, port)

    else:
        raise ValueError(f"Controller passthrough not supported for protocol: {protocol}")

    transport.connect(timeout=5.0)
    try:
        transport.send(cmd_print(escpos_data))
    finally:
        transport.close()


def _print_via_network(escpos_data: bytes, config: dict[str, Any]) -> None:
    """Print via python-escpos Network printer."""
    ip = config["printer_ip_address"]
    port = config.get("printer_port", 9100)

    try:
        from escpos.printer import Network
    except ImportError:
        raise ImportError("python-escpos is required for network printing. Install with: pip install python-escpos")

    printer = Network(ip, port=port)
    try:
        printer._raw(escpos_data)
        printer.close()
    except Exception:
        printer.close()
        raise


def _ticket_escpos_sequence(
    p,
    *,
    barcode: str,
    gate_name: str,
    site_name: str,
    date_str: str,
    time_str: str,
    additional_info: str = "",
) -> None:
    """Shared ticket layout for any python-escpos printer object."""
    site = site_name or ""

    p.set(align="center")
    p.text("TIKET PARKIR\n")

    if site:
        # ESC ! 0x10 = double height (as old parking.py); library set() size is
        # ignored by this clone.
        p._raw(b"\x1b!\x10")
        for i in range(0, len(site), 32):
            p.text(f"{site[i:i + 32]}\n")
        p._raw(b"\x1b!\x00")
        p.text("\n")  # gap between header and info block

    p.set(width=1, height=1, align="left")
    block = " " * TICKET_BLOCK_INDENT
    p.text(f"{block}GATE         : {gate_name}\n")
    p.text(f"{block}TANGGAL      : {date_str}\n")
    p.text(f"{block}JAM          : {time_str}\n\n")

    # Raster (force_software) prints as junk text on this clone, and format A
    # (NUL-terminated) drops the bars. Format B (GS k 69 n data) is what the
    # old working parking.py sent. ESC a 1 centres barcode + footer (my earlier
    # edit dropped the p.set(align="center") that did this).
    p._raw(b"\x1b\x61\x01")
    p._raw(b"\x1dh\x64\x1dH\x02\x1dk\x45" + bytes([len(barcode)]) + barcode.encode())
    p.text("\n\n")  # gap between barcode and footer
    p.text("JANGAN TINGGALKAN BARANG BAWAAN ANDA\n")
    p.text(f"-{site}-\n")
    if additional_info:
        p.text(f"{additional_info}\n")
    p._raw(b"\x1b\x61\x00")  # back to left; printer keeps state between jobs
    # cut(feed=True) already feeds 6 lines; stacking "\n"s on top left ~10 blank
    # lines. GS V 66 0 feeds exactly to the blade, so one line is enough.
    p.text("\n")
    p.cut(feed=False)


def _print_ticket_via_usb_printer(
    device: str,
    barcode: str,
    gate_name: str,
    site_name: str,
    timestamp: str = "",
    additional_info: str = "",
) -> None:
    """Print the entry ticket through python-escpos (USB device)."""
    from datetime import datetime

    from escpos.printer import File

    date_str, time_str = _split_ticket_datetime(timestamp)
    if not timestamp:
        now = datetime.now()
        date_str, time_str = now.strftime("%d-%b-%Y"), now.strftime("%H:%M:%S")
    else:
        try:
            date_str = datetime.fromisoformat(timestamp).strftime("%d-%b-%Y")
        except ValueError:
            pass

    p = File(device)
    try:
        _ticket_escpos_sequence(
            p,
            barcode=barcode,
            gate_name=gate_name,
            site_name=site_name,
            date_str=date_str,
            time_str=time_str,
            additional_info=additional_info,
        )
    finally:
        p.close()


def _print_ticket_via_network_printer(
    host: str,
    port: int,
    barcode: str,
    gate_name: str,
    site_name: str,
    timestamp: str = "",
    additional_info: str = "",
) -> None:
    """Print the entry ticket through python-escpos over TCP (port 9100)."""
    from datetime import datetime

    from escpos.printer import Network

    date_str, time_str = _split_ticket_datetime(timestamp)
    if not timestamp:
        now = datetime.now()
        date_str, time_str = now.strftime("%d-%b-%Y"), now.strftime("%H:%M:%S")
    else:
        try:
            date_str = datetime.fromisoformat(timestamp).strftime("%d-%b-%Y")
        except ValueError:
            pass

    p = Network(host, port=port or 9100)
    try:
        _ticket_escpos_sequence(
            p,
            barcode=barcode,
            gate_name=gate_name,
            site_name=site_name,
            date_str=date_str,
            time_str=time_str,
            additional_info=additional_info,
        )
    finally:
        p.close()


def _print_via_usb(escpos_data: bytes, config: dict[str, Any]) -> None:
    """Write ESC/POS bytes straight to a usblp device (/dev/usb/lp0, lp1, ...).

    USB thermal printers expose a character device; no driver needed.
    """
    import os

    device = config.get("printer_device")
    if not device:
        raise ValueError("USB printer device path is not configured")
    if not os.path.exists(device):
        raise FileNotFoundError(f"{device} not found — printer unplugged?")
    fd = os.open(device, os.O_WRONLY)
    try:
        os.write(fd, escpos_data)
    finally:
        os.close(fd)


def _print_via_serial(escpos_data: bytes, config: dict[str, Any]) -> None:
    """Print via python-escpos Serial printer."""
    device = config["printer_device"]
    baudrate = config.get("baudrate", 9600)

    try:
        from escpos.printer import Serial
    except ImportError:
        raise ImportError("python-escpos is required for serial printing. Install with: pip install python-escpos")

    printer = Serial(devfile=device, baudrate=baudrate)
    try:
        printer._raw(escpos_data)
        printer.close()
    except Exception:
        printer.close()
        raise
