"""Unified daemon CLI entry point.

Launches GateInDaemon for IN gates. OUT gates are driven by booth_bridge
(serial relay + readers on booth PC) — no daemon runs for OUT direction.

Usage:
    python -m daemons.cli --gate-id GIN01
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is on path when run as module
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

logger = get_logger("daemon_cli")


async def _build_config(session: AsyncSession, gate_code: str, *, quiet: bool = False) -> dict:
    """Fetch gate config from DB and flatten into dict for daemon consumption."""
    # Import here to avoid circulars and ensure models are registered
    from api.app.models.gate import Gate

    result = await session.execute(select(Gate).where(Gate.code == gate_code))
    gate = result.scalar_one_or_none()

    if gate is None:
        raise RuntimeError(f"Gate with code '{gate_code}' not found in database")

    # Base config from flat columns
    config = {
        "id": gate.id,
        "name": gate.name,
        "code": gate.code,
        "direction": gate.direction,
        "area_parkir_id": gate.area_parkir_id,
        "pos_id": gate.pos_id,
        "protocol": gate.protocol,
        "controller_host": gate.controller_host,
        "controller_port": gate.controller_port,
        "controller_device": gate.controller_device,
        "controller_baudrate": gate.controller_baudrate,
        "has_close_sensor": gate.has_close_sensor,
        "gate_close_duration_ms": gate.gate_close_duration_ms,
        "relay_mode": gate.relay_mode,
        "gate_open_timeout_s": gate.gate_open_timeout_s,
        "sensor_stuck_s": gate.sensor_stuck_s,
        "is_active": gate.is_active,
        "is_online": gate.is_online,
    }

    # Merge hardware_config JSONB (direction-specific settings)
    hw = gate.hardware_config or {}
    config["hardware_config"] = hw

    # Flatten common hardware_config values for backward compatibility
    config["gate_mode"] = hw.get("gate_mode", "CASH")
    config["emoney_minimum_balance"] = hw.get("emoney_minimum_balance", 10000)
    config["print_decision_timeout_seconds"] = hw.get("print_decision_timeout_seconds", 10)
    config["payment_timeout_seconds"] = hw.get("payment_timeout_seconds", 120)
    config["open_command"] = hw.get("open_command")
    config["close_command"] = hw.get("close_command")
    config["pulse_duration_ms"] = hw.get("pulse_duration_ms")

    # Lane reset timer: per-gate hardware_config override wins, else the global
    # setting, else 5s. Clears the IN3 loop latch without waiting for IN3OFF.
    lane_reset = hw.get("lane_reset_seconds")
    if lane_reset is None:
        from api.app.models.setting import Setting

        setting_row = (
            await session.execute(
                select(Setting).where(Setting.key == "lane_reset_seconds")
            )
        ).scalar_one_or_none()
        lane_reset = setting_row.value if setting_row is not None else None
    try:
        config["lane_reset_seconds"] = max(1, int(lane_reset))
    except (TypeError, ValueError):
        config["lane_reset_seconds"] = 5

    # Lane reset trigger: timer / IN3OFF / both (per-gate override first).
    lane_mode = hw.get("lane_reset_mode")
    if lane_mode is None:
        from api.app.models.setting import Setting

        mode_row = (
            await session.execute(
                select(Setting).where(Setting.key == "lane_reset_mode")
            )
        ).scalar_one_or_none()
        lane_mode = mode_row.value if mode_row is not None else None
    lane_mode = str(lane_mode or "time").strip().lower()
    config["lane_reset_mode"] = lane_mode if lane_mode in ("time", "in3off", "both") else "time"

    if not quiet:
        logger.info(
            "gate_config_loaded",
            gate_id=gate_code,
            direction=gate.direction,
            protocol=gate.protocol,
            host=gate.controller_host,
            port=gate.controller_port,
        )

    # Active ticket printer for this gate. The in-flow cash print must use the
    # same transport the print worker uses: NETWORK/SERIAL printers are printed
    # by the worker (the daemon only enqueues), CONTROLLER_PASSTHROUGH must be
    # printed by the daemon because it already owns the single TCP socket.
    from api.app.models.printer import Printer

    printer_result = await session.execute(
        select(Printer).where(
            Printer.gate_id == gate_code,
            Printer.gate_type == "IN",
            Printer.is_active == True,  # noqa: E712
        ).order_by(Printer.id)
    )
    # A gate may have several printers; the oldest wins, as in print_worker.
    printer = printer_result.scalars().first()

    # Shared printer referenced from the gate form wins over gate-bound rows.
    pid = (gate.hardware_config or {}).get("printer_id") if gate else None
    if pid:
        try:
            from api.app.models.printer import Printer as _Printer

            shared = await session.get(_Printer, int(pid))
            if shared is not None:
                printer = shared
        except (TypeError, ValueError):
            pass

    config["printer"] = (
        {
            "mode": printer.mode,
            "ip_address": printer.ip_address,
            "port": printer.port,
            "serial_device": printer.serial_device,
            "baudrate": printer.baudrate,
        }
        if printer is not None
        else None
    )

    # Site name for the printed ticket header/footer.
    try:
        from api.app.models.site_config import SiteConfig

        site_result = await session.execute(select(SiteConfig).limit(1))
        site_cfg = site_result.scalar_one_or_none()
        config["site_name"] = (site_cfg.name if site_cfg and site_cfg.name else "") or ""
    except Exception:
        config["site_name"] = ""

    return config


async def _run_daemon(gate_code: str) -> None:
    """Lookup gate, instantiate daemon, and run until shutdown."""
    settings = get_settings()
    configure_logging()

    # Independent DB engine for daemon (never import api.database)
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=2,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    config: dict | None = None
    direction: str | None = None

    async with session_factory() as session:
        config = await _build_config(session, gate_code)
        direction = config["direction"]

    async def load_config() -> dict | None:
        """Re-read the gate row for live reloads (no restart needed)."""
        try:
            async with session_factory() as session:
                return await _build_config(session, gate_code, quiet=True)
        except RuntimeError:
            return None

    # Instantiate correct daemon based on direction
    if direction == "IN":
        from daemons.gate_in import GateInDaemon

        daemon = GateInDaemon(
            gate_id=gate_code, config=config, config_loader=load_config
        )
    elif direction == "OUT":
        # booth_bridge owns serial relay + RFID/e-money readers on the booth PC.
        # No daemon runs for OUT gates.
        logger.info("gate_out_skipped_booth_bridge_mode", gate_id=gate_code)
        return
    else:
        raise RuntimeError(f"Unknown gate direction: {direction}")

    # Daemon handles its own signal handling, task cancellation, Redis close
    try:
        await daemon.run()
    finally:
        await engine.dispose()
    logger.info("daemon_shutdown_complete", gate_id=gate_code)


def main() -> int:
    parser = argparse.ArgumentParser(description="E-Parking v2 Gate Daemon Runner")
    parser.add_argument("--gate-id", required=True, help="Gate code from database (e.g. GIN01)")
    args = parser.parse_args()

    try:
        asyncio.run(_run_daemon(args.gate_id))
    except RuntimeError as e:
        logger.error("daemon_fatal_error", error=str(e))
        return 1
    except Exception:
        logger.exception("daemon_uncaught_exception")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
