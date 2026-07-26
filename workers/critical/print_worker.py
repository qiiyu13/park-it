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
                )
            )
            printer = result.scalar_one_or_none()
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


def _build_escpos_ticket(
    barcode: str,
    gate_name: str = "",
    location_name: str = "",
    additional_info: str = "",
    timestamp: str = "",
) -> bytes:
    """Build ESC/POS ticket payload.

    Compatible with both controller passthrough and direct printer modes.
    """
    lines = [
        b"\x1b\x61\x01",  # Center align
        b"TIKET PARKIR\n",
        b"\x1b\x21\x10",  # Double height
        f"{location_name}\n\n".encode(),
        b"\x1b\x21\x00",  # Normal height
        b"\x1b\x61\x00",  # Left align
        f"GATE         : {gate_name}\n".encode(),
        f"TANGGAL      : {timestamp}\n".encode(),
        b"\x1b\x61\x01",  # Center align
        b"\x1d\x68\x64",  # Barcode height 100
        b"\x1d\x48\x02",  # Text below barcode
        b"\x1d\x6b\x45",  # CODE39
        bytes([len(barcode)]) + barcode.encode() + b"\x00",
        f"\n{additional_info}\n".encode(),
        b"\x1d\x56\x41",  # Full cut
    ]
    return b"".join(lines)


def _build_escpos_receipt(
    transaction_data: dict[str, Any],
    location_name: str = "",
) -> bytes:
    """Build ESC/POS receipt payload for exit."""
    lines = [
        b"\x1b\x61\x01",  # Center align
        b"STRUK PARKIR\n",
        b"\x1b\x21\x10",  # Double height
        f"{location_name}\n\n".encode(),
        b"\x1b\x21\x00",  # Normal height
        b"\x1b\x61\x00",  # Left align
        f"GATE         : {transaction_data.get('gate_name', '')}\n".encode(),
        f"TANGGAL      : {transaction_data.get('date', '')}\n".encode(),
        f"JAM MASUK    : {transaction_data.get('time_in', '')}\n".encode(),
        f"JAM KELUAR   : {transaction_data.get('time_out', '')}\n".encode(),
        f"DURASI       : {transaction_data.get('duration', '')}\n".encode(),
        f"JENIS        : {transaction_data.get('vehicle_type', '')}\n".encode(),
        f"METODE       : {transaction_data.get('payment_method', '')}\n".encode(),
        b"\x1b\x61\x01",  # Center align
        f"TOTAL        : Rp {transaction_data.get('total_fee', 0):,}\n\n".encode(),
        f"{transaction_data.get('additional_info', '')}\n".encode(),
        b"\x1d\x56\x41",  # Full cut
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
                )
            )
            printer = printer_result.scalar_one_or_none()

            gate_result = await db.execute(select(Gate).where(Gate.code == gate_id))
            gate = gate_result.scalar_one_or_none()

            if printer is None or printer.mode == "CONTROLLER_PASSTHROUGH":
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
        if mode == "CONTROLLER_PASSTHROUGH":
            _print_via_controller(escpos_data, print_config)
        elif mode == "NETWORK":
            _print_via_network(escpos_data, print_config)
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
