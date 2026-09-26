"""Booth Bridge Service — runs on booth PC.

Connects to serial devices (e-money reader, receipt printer, running text),
exposes them via WebSocket for the POS frontend, drives the local serial
relay for boom barrier opens, and runs an autonomous PC/SC reader poll
(Omnikey 5427 CK) for member RFID exits.

Usage:
    python -m booth_bridge.main --config /etc/parking/booth.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import signal
from collections.abc import Awaitable, Callable

from booth_bridge.api_client import ApiClient
from booth_bridge.gate_opener import GateOpener
from booth_bridge.health_server import HealthServer
from booth_bridge.omnikey_poller import OmnikeyPoller
from booth_bridge.outbox import ResultOutbox
from booth_bridge.serial_manager import SerialManager
from booth_bridge.websocket_server import WebSocketServer
from shared.logging import configure_logging, get_logger

logger = get_logger("booth_bridge")


async def _supervise(
    name: str,
    coro_factory: Callable[[], Awaitable[None]],
    *,
    initial_backoff_s: float = 1.0,
    max_backoff_s: float = 30.0,
) -> None:
    """Restart `coro_factory()` whenever it raises. Honors cancellation.

    Each subtask (Omnikey poller loop, WS server lifetime, refresher,
    heartbeat) lives inside its own supervisor so one component's crash
    never kills the whole booth bridge process. Backoff caps at
    ``max_backoff_s`` and resets after a clean run >= 60s (subtask was
    healthy long enough to count as recovered).
    """
    backoff = initial_backoff_s
    while True:
        started = asyncio.get_event_loop().time()
        try:
            await coro_factory()
            logger.warning("supervised_task_returned", task=name)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            ran_for = asyncio.get_event_loop().time() - started
            logger.exception(
                "supervised_task_crashed",
                task=name,
                ran_for_s=round(ran_for, 2),
                error=str(e),
            )
            if ran_for >= 60.0:
                backoff = initial_backoff_s
        # Sleep on BOTH crash and clean return — a coroutine that returns
        # immediately (e.g. a closed WS server object) would otherwise spin
        # at full CPU while port 5678 stays dead.
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff_s)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/parking/booth.json")
    parser.add_argument("--port", type=int, default=5678)
    parser.add_argument(
        "--health-port",
        type=int,
        default=5679,
        help="HTTP /health bind port (localhost only)",
    )
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    # Use shared structlog so booth logs match server format (JSON + trace_id
    # in prod, console in dev). configure_logging reads APP_ENV/LOG_LEVEL from
    # .env; booth_bridge.service sets EnvironmentFile so settings load cleanly.
    configure_logging()

    logger.info("starting_booth_bridge", port=args.port, booth=config.get("name"))

    serial_manager = SerialManager(config.get("peripherals", {}))
    await serial_manager.start()

    api_config = None
    api_client: ApiClient | None = None
    if config.get("api_base_url") and config.get("api_key"):
        api_config = {"base_url": config["api_base_url"], "api_key": config["api_key"]}
        api_client = ApiClient(api_config["base_url"], api_config["api_key"])

    gate_opener: GateOpener | None = None
    rfid_poller: OmnikeyPoller | None = None
    gate_code = config.get("default_gate_code")
    ws_server_ref: list = [None]

    def _gate_signature(g: dict) -> tuple:
        # Fields whose change forces a GateOpener rebuild. Code + everything
        # gate_opener actually reads from gate_data. Anything else (e.g.
        # transient last_heartbeat) is intentionally ignored so we don't
        # rebuild every minute for noise.
        hw = g.get("hardware_config") or {}
        return (
            g.get("code", ""),
            g.get("controller_device") or hw.get("device", ""),
            int(g.get("controller_baudrate") or hw.get("baudrate", 0) or 0),
            hw.get("open_command") or g.get("open_command", ""),
            hw.get("close_command") or g.get("close_command", ""),
            float(hw.get("close_delay_seconds", 3) or 0),
        )

    # Broadcast helper defined once so both the boot path and the refresher
    # (which may start a poller mid-flight) push events through the same
    # ws_server reference.
    async def _broadcast(payload: dict) -> None:
        if ws_server_ref[0] is not None:
            await ws_server_ref[0].broadcast(payload)

    def _build_poller(gate_data: dict, opener: GateOpener) -> OmnikeyPoller | None:
        hw = gate_data.get("hardware_config") or {}
        omnikey_cfg = hw.get("omnikey_reader") or {}
        if not omnikey_cfg.get("enabled"):
            return None
        return OmnikeyPoller(
            gate_id=gate_data.get("code", ""),
            gate_db_id=gate_data.get("id", 0),
            api_client=api_client,
            gate_opener=opener,
            broadcast=_broadcast,
            device_path=omnikey_cfg.get("device_path"),
            device_name_match=omnikey_cfg.get("device_name_match", "omnikey"),
            dedupe_cooldown_s=float(omnikey_cfg.get("dedupe_cooldown_s", 3.0)),
            flush_idle_ms=int(omnikey_cfg.get("flush_idle_ms", 200)),
            min_card_len=int(omnikey_cfg.get("min_card_len", 6)),
            min_invalid_feedback_len=int(
                omnikey_cfg.get("min_invalid_feedback_len", 3)
            ),
        )

    boot_signature: tuple | None = None
    if api_client and gate_code:
        gate_data = await api_client.fetch_gate(gate_code)
        if gate_data:
            gate_opener = GateOpener(gate_data)
            boot_signature = _gate_signature(gate_data)
            logger.info("gate_opener_ready", gate=gate_code)
            rfid_poller = _build_poller(gate_data, gate_opener)
        else:
            logger.warning(
                "gate_fetch_failed_at_boot_will_retry_in_refresher",
                gate_code=gate_code,
            )

    # Durable queue for e-money results: the card is debited before the API
    # hears about it, so results must survive API outages and bridge crashes.
    outbox: ResultOutbox | None = None
    outbox_dir = config.get("outbox_dir", "/var/lib/parking-bridge/outbox")
    try:
        outbox = ResultOutbox(outbox_dir)
    except OSError as e:
        logger.error("outbox_init_failed_results_will_not_be_durable", error=str(e), dir=outbox_dir)

    ws_server = WebSocketServer(
        serial_manager,
        port=args.port,
        api_config=api_config,
        gate_opener=gate_opener,
        outbox=outbox,
    )
    ws_server_ref[0] = ws_server
    await ws_server.start()

    async def _drain_outbox() -> None:
        """Re-drive undelivered e-money results until the queue is empty."""
        while True:
            await asyncio.sleep(30)
            assert outbox is not None
            for payload in outbox.pending():
                try:
                    status, body = await asyncio.to_thread(ws_server._post_booth_result_sync, payload)
                except Exception as e:
                    logger.warning("outbox_drain_post_failed", error=str(e))
                    break  # API still down — back off until next tick
                if status == 200:
                    outbox.remove(payload)
                    logger.info(
                        "outbox_drain_delivered",
                        status=payload.get("status"),
                        transaction_id=payload.get("transaction_id"),
                    )
                elif 400 <= status < 500:
                    # Deterministic rejection: keep for manual inspection but
                    # stop hammering — skip the rest this tick too? No: other
                    # entries may be fine, so just drop this one from the loop.
                    logger.error(
                        "outbox_drain_rejected",
                        status=status,
                        body=body[:300],
                        transaction_id=payload.get("transaction_id"),
                    )
                else:
                    break  # 5xx — server unhealthy, retry next tick

    if rfid_poller is not None:
        rfid_poller.start()
        logger.info("rfid_poller_started")

    # Mutable containers so the refresher can swap the live GateOpener AND
    # spin up the OmnikeyPoller mid-flight without restarting the process.
    # heartbeat, snapshot, and shutdown all read through these containers.
    gate_opener_state: dict = {
        "opener": gate_opener,
        "signature": boot_signature,
    }
    rfid_poller_state: dict = {"poller": rfid_poller}
    # Forward-declared so _refresh_gate_config can register a new supervisor
    # task when it boots an Omnikey poller mid-flight. Populated below before
    # the refresher first ticks.
    supervisors: list[asyncio.Task] = []

    async def _refresh_gate_config() -> None:
        """Re-fetch gate row every 60s.

        Handles three cases:
        1. Cold-start with API down — gate_opener was None; build it once API
           comes back. If gate config also enables Omnikey, start the poller
           mid-flight and register its supervisor.
        2. Live edit in admin UI — operator changes open_command /
           close_delay / device; refresher rebuilds GateOpener and rewires
           ws_server + the existing rfid_poller without restart.
        3. Admin enables omnikey_reader on a gate that didn't have one at
           boot. Refresher boots the poller + registers its supervisor.
        """
        if not (api_client and gate_code):
            return
        while True:
            await asyncio.sleep(60)
            try:
                gate_data = await api_client.fetch_gate(gate_code)
            except Exception as e:
                logger.warning("gate_refresh_fetch_failed", error=str(e))
                continue
            if not gate_data:
                logger.warning("gate_refresh_no_data", gate_code=gate_code)
                continue
            new_sig = _gate_signature(gate_data)
            cur_sig = gate_opener_state.get("signature")
            opener_changed = (
                cur_sig != new_sig or gate_opener_state.get("opener") is None
            )

            if opener_changed:
                new_opener = GateOpener(gate_data)
                gate_opener_state["opener"] = new_opener
                gate_opener_state["signature"] = new_sig
                ws_server.gate_opener = new_opener
                poller = rfid_poller_state.get("poller")
                if poller is not None:
                    poller.opener = new_opener
                logger.info(
                    "gate_opener_refreshed",
                    gate=gate_code,
                    cold_start=cur_sig is None,
                )

            # Try to bring up Omnikey poller if config now enables it and we
            # don't already have one running. Reuse the live opener (which
            # may have just been swapped above).
            if rfid_poller_state.get("poller") is None:
                live_opener = gate_opener_state.get("opener")
                if live_opener is not None:
                    fresh_poller = _build_poller(gate_data, live_opener)
                    if fresh_poller is not None:
                        fresh_poller.start()
                        rfid_poller_state["poller"] = fresh_poller
                        logger.info("rfid_poller_started_mid_flight", gate=gate_code)

                        async def _omnikey_factory() -> None:
                            p = rfid_poller_state.get("poller")
                            if p is None:
                                return
                            if p._task is None or p._task.done():
                                p.start()
                            assert p._task is not None
                            await p._task

                        supervisors.append(
                            asyncio.create_task(
                                _supervise("omnikey_poller", _omnikey_factory),
                                name="sup_omnikey_mid_flight",
                            )
                        )

    async def _hardware_status_heartbeat() -> None:
        while True:
            # Read live opener + poller — refresher may have swapped/started
            # either of them since boot.
            live_opener = gate_opener_state.get("opener")
            live_poller = rfid_poller_state.get("poller")
            payload = {
                "type": "hardware_status",
                "rfid": {"connected": bool(live_poller and live_poller.connected)},
                "palang": {"connected": bool(live_opener and live_opener.is_present())},
            }
            try:
                await ws_server.broadcast(payload)
            except Exception as e:
                # Caught here so a single broadcast failure doesn't tear down
                # the heartbeat; the supervisor wrapper handles the case where
                # the whole coroutine raises something we couldn't anticipate.
                logger.warning("hardware_status_broadcast_failed", error=str(e))
            await asyncio.sleep(5)

    async def _ws_serve_lifetime() -> None:
        """Wait for ws_server's underlying serve task to terminate, then rebind.

        websockets.serve() already starts the server in `ws_server.start()`,
        so we block on its closed event. If the listener dies (kernel evicts
        it, OS file table exhausted, etc.) we rebuild it — without this the
        port stays dead while systemd sees a healthy process, and every POS
        payment in the booth fails.
        """
        srv = ws_server._server
        if srv is None:
            # Should never happen — we awaited start() above — but treat as a
            # transient so supervisor retries instead of crashing the loop.
            await asyncio.sleep(1)
            raise RuntimeError("ws_server has no underlying server object")
        await srv.wait_closed()
        logger.warning("ws_server_listener_closed_restarting")
        await ws_server.start()

    # Booth bridge version exposed in health snapshot + heartbeat. Read at
    # boot — bumping the package re-execs the systemd unit, so it's stable
    # for the life of this process.
    try:
        from importlib.metadata import version as _pkg_version

        bridge_version = _pkg_version("parking-system-v2")
    except Exception:
        bridge_version = "unknown"

    def _snapshot() -> dict:
        live_opener = gate_opener_state.get("opener")
        live_poller = rfid_poller_state.get("poller")
        return {
            "status": "ok",
            "booth": {
                "code": config.get("code"),
                "name": config.get("name"),
            },
            "gate": {
                "code": getattr(live_opener, "gate_id", None) if live_opener else None,
                "configured": live_opener is not None,
                "present": bool(live_opener and live_opener.is_present()),
            },
            "rfid": {
                "connected": bool(live_poller and live_poller.connected),
                "last_card_at": (
                    live_poller._last_card_at if live_poller else None
                ),
            },
            "ws": {
                "port": args.port,
                "clients": len(ws_server._clients),
            },
            "bridge_version": bridge_version,
        }

    async def _send_heartbeats() -> None:
        """POST snapshot to /api/pos/heartbeat every 15s.

        Bound to the configured booth code from booth.json; the server
        rejects unknown codes (the wizard owns registration), so a missing
        code in config is a fatal misconfig — log loudly and exit so
        supervisor restarts pick up a fixed config after the tech edits it.
        """
        if api_client is None:
            return
        booth_code = config.get("code")
        if not booth_code:
            logger.error(
                "heartbeat_disabled_missing_booth_code "
                "(set 'code' in /etc/parking/booth.json)"
            )
            return
        while True:
            snap = _snapshot()
            payload = {
                "booth_code": booth_code,
                "rfid_connected": snap["rfid"]["connected"],
                "gate_connected": snap["gate"]["present"],
                "ws_clients": snap["ws"]["clients"],
                "last_card_at": snap["rfid"]["last_card_at"],
                "bridge_version": bridge_version,
            }
            await api_client.heartbeat(payload)
            await asyncio.sleep(15)

    health_server = HealthServer(_snapshot, port=args.health_port)
    await health_server.start()

    # Supervisor loops: any of these can crash without taking down the booth
    # process. Backoff resets after 60s of healthy runtime. The list itself
    # was forward-declared above so the refresher can append a poller
    # supervisor when it boots Omnikey mid-flight.
    supervisors.append(
        asyncio.create_task(
            _supervise("ws_server_lifetime", _ws_serve_lifetime),
            name="sup_ws_server",
        )
    )
    supervisors.append(
        asyncio.create_task(
            _supervise("health_server_lifetime", health_server.serve_forever),
            name="sup_health_server",
        )
    )
    supervisors.append(
        asyncio.create_task(
            _supervise("hardware_status_heartbeat", _hardware_status_heartbeat),
            name="sup_hw_heartbeat",
        )
    )

    if api_config and outbox is not None:
        supervisors.append(
            asyncio.create_task(
                _supervise("outbox_drain", _drain_outbox),
                name="sup_outbox_drain",
            )
        )
        # Replay entries left over from a previous run (crash between deduct
        # and delivery) immediately instead of waiting for the first tick.
        for stale in outbox.pending():
            logger.warning(
                "outbox_replaying_stale_entry",
                status=stale.get("status"),
                transaction_id=stale.get("transaction_id"),
            )

    if rfid_poller is not None:
        poller_ref = rfid_poller  # mypy: capture non-None binding

        async def _omnikey_factory() -> None:
            if poller_ref._task is None or poller_ref._task.done():
                poller_ref.start()
            assert poller_ref._task is not None
            await poller_ref._task

        supervisors.append(
            asyncio.create_task(
                _supervise("omnikey_poller", _omnikey_factory),
                name="sup_omnikey",
            )
        )

    if api_client and gate_code:
        supervisors.append(
            asyncio.create_task(
                _supervise("gate_config_refresher", _refresh_gate_config),
                name="sup_gate_refresh",
            )
        )

    if api_client and config.get("code"):
        supervisors.append(
            asyncio.create_task(
                _supervise("api_heartbeat", _send_heartbeats),
                name="sup_api_heartbeat",
            )
        )

    # Graceful shutdown: systemd sends SIGTERM, Ctrl+C sends SIGINT. Setting
    # the event lets the main coroutine fall through to its finally block,
    # which releases serial ports + closes WS sockets in order. Without this
    # the loop would only exit on KeyboardInterrupt (Ctrl+C from a tty), so a
    # systemd `stop` would wait the full TimeoutStopSec for SIGKILL.
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop(signame: str) -> None:
        if not stop_event.is_set():
            logger.info("shutdown_signal_received", signal=signame)
            stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            # NotImplementedError on platforms without add_signal_handler
            # (Windows). Booth PCs are Ubuntu, but keep the guard for tests.
            loop.add_signal_handler(sig, _request_stop, sig.name)

    try:
        await stop_event.wait()
    finally:
        logger.info("shutdown_starting")
        for sup in supervisors:
            sup.cancel()
        if supervisors:
            await asyncio.gather(*supervisors, return_exceptions=True)
        live_poller = rfid_poller_state.get("poller")
        if live_poller is not None:
            await live_poller.stop()
        await ws_server.stop()
        await health_server.stop()
        await serial_manager.stop()
        logger.info("shutdown_complete")


if __name__ == "__main__":
    asyncio.run(main())
