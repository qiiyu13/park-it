"""Gate-in daemon — combined entry state machine.

Single WAITING_INPUT state handles entry payment methods: ticket button (cash)
and Wiegand W/X (RFID member). E-money no longer participates at entry — it is
exit-only (driver presents printed ticket, taps card at exit).

States: IDLE → WAITING_INPUT → method branch → OPENING → IDLE
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from daemons.base import BaseDaemon
from protocols.compass.parser import parse_stat
from protocols.compass.protocol import (
    CompassTransport,
    SerialTransport,
    cmd_ack,
    cmd_close1,
    cmd_ds,
    cmd_dsu,
    cmd_mt,
    cmd_open1,
    cmd_pr3,
    cmd_rss,
    cmd_stat,
    cmd_stop1,
    cmd_trig1,
)
from shared.events import (
    BaseEvent,
    PlayAudioEvent,
    RfidCardReadEvent,
    VehicleDetectedEvent,
)
from shared.logging import get_logger

logger = get_logger(__name__)

# State constants
STATE_IDLE = "IDLE"
STATE_WAITING_INPUT = "WAITING_INPUT"
STATE_VALIDATING = "VALIDATING"
STATE_PROCESSING = "PROCESSING"
STATE_OPENING = "OPENING"


class GateInDaemon(BaseDaemon):
    """Gate-in daemon for vehicle entry processing."""

    def __init__(
        self,
        gate_id: str,
        config: dict[str, Any],
        *,
        config_loader=None,
    ) -> None:
        super().__init__(gate_id, config, config_loader=config_loader)
        self.hw = config.get("hardware_config", {})
        self.has_rfid = self.hw.get("rfid", {}).get("enabled", False)
        self.has_ticket_printer = self.hw.get("ticket_printer", {}).get("enabled", False)

        self.controller: CompassTransport | SerialTransport | None = None
        self._controller_lock = asyncio.Lock()
        self._poll_task: asyncio.Task | None = None
        self._validating_task: asyncio.Task | None = None
        self._processing_task: asyncio.Task | None = None
        self._in1_on = False
        # Momentary-button installs release IN1 immediately, so IN2 (ticket
        # button) must not depend on _in1_on alone: remember when IN1 last
        # fired and treat IN2 within this window as "vehicle present".
        self._last_in1_at = 0.0
        # IN3 loop detector + IN4 help button state/debounce.
        self._loop_occupied = False
        self._last_in3_at = 0.0
        # Loop latch auto-clear (config: lane_reset_seconds). Controllers that
        # never send IN3OFF would otherwise block the next vehicle until the
        # hardcoded timeout (or forever). Tunable per site/gate.
        try:
            self._lane_reset_seconds = max(1, int(config.get("lane_reset_seconds") or 5))
        except (TypeError, ValueError):
            self._lane_reset_seconds = 5
        # What may release the IN3 loop latch: "time", "in3off", or "both".
        mode = str(config.get("lane_reset_mode") or "time").strip().lower()
        self._lane_reset_mode = mode if mode in ("time", "in3off", "both") else "time"
        self._loop_timer_done = False
        self._loop_in3off = False
        self._last_help_at = 0.0
        # One ticket per IN1 cycle: IN1 arms the ticket button, IN2 consumes it.
        self._ticket_armed = False
        self._last_in2_at = 0.0

        # Circuit breaker for controller send: if N consecutive send errors,
        # fast-fail subsequent sends for `cooldown_s` instead of waiting for
        # each socket-write timeout. The STAT heartbeat will re-probe the
        # controller; a successful send (heartbeat or otherwise) resets state.
        self._cb_fail_count = 0
        self._cb_threshold = 3
        self._cb_cooldown_s = 15.0
        self._cb_open_until = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        await self._connect_controller()
        await super().run()

    async def _on_started(self) -> None:
        if self.state != STATE_IDLE:
            logger.warning("startup_state_reset", gate_id=self.gate_id, old_state=self.state)
            await self._transition(STATE_IDLE)
        await self._start_polling()

    async def stop(self) -> None:
        await super().stop()
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        await self._disconnect_controller()

    def get_initial_state(self) -> str:
        return STATE_IDLE

    def _controller_ok(self) -> bool:
        """Heartbeat liveness — true only when the controller link is up.

        Lets monitoring distinguish "daemon alive but gate hardware unreachable"
        from a fully healthy gate.
        """
        return bool(self.controller and self.controller.is_connected())

    # ------------------------------------------------------------------
    # Controller connection
    # ------------------------------------------------------------------

    async def _connect_controller(self) -> None:
        protocol = self.config.get("protocol", "compass")
        try:
            if protocol == "serial":
                device = self.config.get("controller_device")
                baudrate = self.config.get("controller_baudrate", 9600)
                if not device:
                    logger.warning("no_controller_config", gate_id=self.gate_id, protocol=protocol)
                    return
                self.controller = SerialTransport(device, baudrate)
                self.controller.connect(timeout=5.0)
                logger.info("controller_connected", gate_id=self.gate_id, device=device, baudrate=baudrate)
            else:
                host = self.config.get("controller_host")
                port = self.config.get("controller_port")
                if not host or not port:
                    logger.warning("no_controller_config", gate_id=self.gate_id, protocol=protocol)
                    return
                self.controller = CompassTransport(host, port)
                self.controller.connect(timeout=5.0)
                logger.info("controller_connected", gate_id=self.gate_id, host=host, port=port)
        except Exception as e:
            logger.error("controller_connect_failed", gate_id=self.gate_id, error=str(e))
            self.controller = None

    async def _disconnect_controller(self) -> None:
        if self.controller:
            # RST, not FIN: frees the single-client controller's slot at once
            # (see CompassTransport.abort). Covers stop(), reconnect, config edit.
            self.controller.abort()
            self.controller = None
            logger.info("controller_disconnected", gate_id=self.gate_id)

    async def _on_config_reloaded(self, connection_changed: bool) -> None:
        """Apply admin edits in place; reconnect the controller if its link moved."""
        self.hw = self.config.get("hardware_config", {})
        self.has_rfid = self.hw.get("rfid", {}).get("enabled", False)
        self.has_ticket_printer = self.hw.get("ticket_printer", {}).get("enabled", False)
        try:
            self._lane_reset_seconds = max(
                1, int(self.config.get("lane_reset_seconds") or 5)
            )
        except (TypeError, ValueError):
            self._lane_reset_seconds = 5
        mode = str(self.config.get("lane_reset_mode") or "time").strip().lower()
        self._lane_reset_mode = mode if mode in ("time", "in3off", "both") else "time"

        if not connection_changed:
            return

        async with self._controller_lock:
            await self._disconnect_controller()
        # The RSS listener notices the dead socket and reconnects using the new
        # protocol/host/port within ~0.5s. Reset the fast-fail breaker so the
        # first command after an edit is not dropped.
        self._cb_fail_count = 0
        self._cb_open_until = 0.0
        logger.info(
            "controller_reconnect_for_config",
            gate_id=self.gate_id,
            protocol=self.config.get("protocol"),
            host=self.config.get("controller_host"),
            port=self.config.get("controller_port"),
            device=self.config.get("controller_device"),
        )

    # ------------------------------------------------------------------
    # Relay mode helpers
    # ------------------------------------------------------------------

    async def _relay_open(self) -> bool:
        """Fire the open relay. Returns True only if the command reached the
        controller (write succeeded), False if dropped/skipped."""
        relay_mode = self.config.get("relay_mode", "SINGLE")
        if relay_mode == "SINGLE":
            return await self._send_controller_command(cmd_trig1())
        return await self._send_controller_command(cmd_open1())

    async def _relay_open_reliable(self) -> bool:
        """Open the relay with bounded retry to ride out a brief controller
        reconnect (the ~1s window after a TCP drop). The relay pulse is
        idempotent, so retrying is safe — a repeated TRIG1/OPEN1 is harmless.

        Returns True as soon as a write lands; False only if every attempt
        failed (controller hard-down — operator intervention needed).
        """
        attempts = 5
        for i in range(attempts):
            if await self._relay_open():
                return True
            if i < attempts - 1:
                logger.warning(
                    "relay_open_retry", gate_id=self.gate_id, attempt=i + 1, of=attempts
                )
                await asyncio.sleep(0.8)
        return False

    async def _relay_close(self) -> None:
        if self.config.get("relay_mode") in ("DUAL", "TRIPLE"):
            await self._send_controller_command(cmd_close1())

    async def _relay_brake(self) -> None:
        if self.config.get("relay_mode") == "TRIPLE":
            await self._send_controller_command(cmd_stop1())

    async def _display(self, line1: str = "", line2: str = "") -> None:
        if self.hw.get("display", {}).get("enabled", True):
            cmd = cmd_dsu() if not line1 else cmd_ds(line1, line2)
            await self._send_controller_command(cmd)

    # ------------------------------------------------------------------
    # RSS listener
    # ------------------------------------------------------------------

    async def _start_polling(self) -> None:
        self._poll_task = self._spawn_tracked(self._rss_listener(), name="poll")
        self._spawn_tracked(self._controller_heartbeat(), name="ctrl_hb")
        if self.has_rfid and self.hw.get("rfid", {}).get("connection") == "direct_serial":
            self._spawn_tracked(self._rfid_serial_reader_task(), name="rfid_serial")

    async def _controller_heartbeat(self) -> None:
        """Send periodic STAT to keep controller's connected-client state alive.

        Compass controller LED flashes rapidly if it doesn't see PC-side
        traffic, even with TCP socket open. STAT every 5s is enough.
        """
        while self._running:
            try:
                await asyncio.sleep(5)
                if self.controller and self.controller.is_connected():
                    await self._send_controller_command(cmd_stat())
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("controller_heartbeat_error", gate_id=self.gate_id, error=str(e))

    async def _setup_rss(self) -> None:
        async with self._controller_lock:
            controller = self.controller
            if not (controller and controller.is_connected()):
                return
            controller.send(cmd_rss(interval_100ms=2))
        logger.info("rss_configured", gate_id=self.gate_id)

    async def _rss_listener(self) -> None:
        await self._setup_rss()
        buffer = b""
        reconnect_delay = 1.0
        while self._running:
            try:
                if self.controller and self.controller.is_connected():
                    reconnect_delay = 1.0
                    chunk = await self.controller.recv_async(timeout=0.5)
                    if chunk:
                        buffer += chunk
                        buffer = await self._process_rss_buffer(buffer)
                else:
                    # Controller down — attempt reconnect with capped backoff
                    # instead of spinning forever on a dead socket. Without this
                    # a single TCP drop leaves the gate dead until manual restart.
                    buffer = b""
                    logger.warning(
                        "rss_controller_down_reconnecting",
                        gate_id=self.gate_id,
                        next_retry_s=reconnect_delay,
                        reason=getattr(self.controller, "last_error", None),
                    )
                    await self._disconnect_controller()
                    await self._connect_controller()
                    if self.controller and self.controller.is_connected():
                        await self._setup_rss()
                        # Fresh socket — clear the circuit breaker so commands flow
                        # immediately instead of waiting out a stale cooldown.
                        self._cb_fail_count = 0
                        self._cb_open_until = 0.0
                        logger.info("rss_controller_reconnected", gate_id=self.gate_id)
                        reconnect_delay = 1.0
                    else:
                        await asyncio.sleep(reconnect_delay)
                        reconnect_delay = min(reconnect_delay * 2, 30.0)
            except asyncio.CancelledError:
                logger.debug("rss_listener_cancelled", gate_id=self.gate_id)
                raise
            except Exception as e:
                logger.error("rss_listener_error", gate_id=self.gate_id, error=str(e))
                await asyncio.sleep(1)

    async def _process_rss_buffer(self, buffer: bytes) -> bytes:
        while len(buffer) >= 2:
            try:
                start = buffer.index(0xA6)
            except ValueError:
                return b""
            try:
                end = buffer.index(0xA9, start + 1)
            except ValueError:
                break
            msg = buffer[start: end + 1]
            buffer = buffer[end + 1:]
            await self._dispatch_rss_message(msg)
        return buffer

    async def _dispatch_rss_message(self, msg: bytes) -> None:
        text = msg.decode("latin-1", errors="ignore")

        if text.rstrip("\xa9").endswith("OK"):
            return

        if "IN1ON" in text:
            self._in1_on = True
            self._last_in1_at = time.monotonic()
            logger.info(
                "input_event", gate_id=self.gate_id, input="IN1",
                state=self.state, loop_occupied=self._loop_occupied,
            )
            if (
                self._loop_occupied
                and self._lane_reset_mode == "time"
                and time.monotonic() - self._last_in3_at > self._lane_reset_seconds
            ):
                # Missed timer task (e.g. daemon hiccup): don't leave the lane
                # latched forever. Only safe in pure timer mode.
                self._loop_occupied = False
                self._loop_timer_done = False
                self._loop_in3off = False
                logger.info(
                    "loop_auto_cleared",
                    gate_id=self.gate_id,
                    seconds=self._lane_reset_seconds,
                    mode=self._lane_reset_mode,
                )
            if self._loop_occupied:
                logger.info("in1_ignored_loop_occupied", gate_id=self.gate_id)
                await self._send_controller_command(cmd_ack("IN1ON"))
                return
            await self._send_controller_command(cmd_ack("IN1ON"))
            if self.state == STATE_IDLE:
                self._ticket_armed = True
                await self._on_vehicle_detected()

        elif "IN1OFF" in text:
            self._in1_on = False
            logger.info("input_event", gate_id=self.gate_id, input="IN1OFF", state=self.state)
            await self._send_controller_command(cmd_ack("IN1OFF"))
            # A momentary button releases within milliseconds — don't treat
            # that release as "vehicle backed up" and drop the lane to IDLE.
            pressed_for = time.monotonic() - self._last_in1_at
            if self.state == STATE_WAITING_INPUT and pressed_for > 2.0:
                await self._on_vehicle_backed_up()
            elif self.state == STATE_OPENING:
                await self._on_vehicle_passed()

        elif "IN2ON" in text:
            logger.info(
                "input_event",
                gate_id=self.gate_id,
                input="IN2",
                state=self.state,
                armed=self._ticket_armed,
            )
            await self._send_controller_command(cmd_ack("IN2ON"))
            # The field flow is strictly: IN1 (vehicle) -> one IN2 press -> ticket.
            # The controller sends no IN2OFF, so one press is one IN2ON frame;
            # debounce repeated frames of the same press.
            if time.monotonic() - self._last_in2_at < 3.0:
                logger.info("in2_debounced", gate_id=self.gate_id)
                return
            self._last_in2_at = time.monotonic()
            # Strict: the vehicle must be ON the loop right now (IN1 asserted).
            # A released IN1 means the car moved on — a later IN2 must not print.
            if not self._in1_on:
                self._ticket_armed = False
            if not self._ticket_armed or not self._in1_on or self.state != STATE_WAITING_INPUT:
                logger.info(
                    "in2_ignored_not_armed",
                    gate_id=self.gate_id,
                    armed=self._ticket_armed,
                    state=self.state,
                )
                return
            self._ticket_armed = False
            await self._on_ticket_button_pressed()

        elif "IN3ON" in text:
            # IN3 = vehicle loop detector behind the barrier. One pass = one
            # transaction: the loop resets the lane to IDLE and marks the loop
            # occupied so a second IN1 cannot start another transaction while
            # the same vehicle still sits on the loop.
            await self._send_controller_command(cmd_ack("IN3ON"))
            logger.info(
                "input_event", gate_id=self.gate_id, input="IN3_LOOP",
                state=self.state, loop_occupied=self._loop_occupied,
            )
            if time.monotonic() - self._last_in3_at < 2.0:
                return  # contact bounce / duplicate frame
            self._last_in3_at = time.monotonic()
            self._loop_occupied = True
            self._loop_timer_done = False
            self._loop_in3off = False
            await self._on_vehicle_passed()

        elif "IN3OFF" in text:
            # Loop released — the vehicle has fully cleared the lane.
            await self._send_controller_command(cmd_ack("IN3OFF"))
            logger.info("input_event", gate_id=self.gate_id, input="IN3_LOOP_OFF", state=self.state)
            self._loop_in3off = True
            self._maybe_clear_loop()

        elif "IN4ON" in text:
            # IN4 = help button. Never touches the transaction or the barrier.
            await self._send_controller_command(cmd_ack("IN4ON"))
            logger.info("input_event", gate_id=self.gate_id, input="IN4_HELP", state=self.state)
            if time.monotonic() - self._last_help_at < 10.0:
                return
            self._last_help_at = time.monotonic()
            await self._on_help_button()

        else:
            parsed = parse_stat(msg)
            if parsed["wiegand_w"] or parsed["wiegand_x"]:
                logger.info(
                    "wiegand_diag",
                    gate_id=self.gate_id,
                    raw_hex=msg.hex(),
                    w=parsed["wiegand_w"],
                    x=parsed["wiegand_x"],
                )
                await self._send_controller_command(cmd_ack("W"))
                if self.has_rfid:
                    vehicle_present = self._in1_on
                    if not vehicle_present:
                        logger.info(
                            "rfid_ignored_no_vehicle",
                            gate_id=self.gate_id,
                            state=self.state,
                        )
                    elif self.state == STATE_WAITING_INPUT:
                        if parsed["wiegand_w"]:
                            await self._on_rfid_card_read(parsed["wiegand_w"], "W")
                        elif parsed["wiegand_x"]:
                            await self._on_rfid_card_read(parsed["wiegand_x"], "X")

    # ------------------------------------------------------------------
    # State transition handlers
    # ------------------------------------------------------------------

    async def _on_vehicle_detected(self) -> None:
        """Vehicle at sensor — go straight to WAITING_INPUT, no gate close."""
        await self._transition(STATE_WAITING_INPUT)
        await self.publish_event(
            VehicleDetectedEvent(event_type="vehicle_detected", gate_id=self.gate_id, sensor="IN1")
        )
        audio_cfg = self.hw.get("audio", {})
        if audio_cfg.get("enabled", True):
            track = audio_cfg.get("welcome_track", 7)  # 7 = "Selamat datang"
            await self._cmd_play_audio(track)
        await self._display("Selamat Datang", "Tombol/Tempel Kartu")

    async def _on_vehicle_backed_up(self) -> None:
        """Vehicle reversed before completing entry."""
        self._ticket_armed = False
        await self._transition(STATE_IDLE)
        await self._display()
        logger.info("vehicle_backed_up", gate_id=self.gate_id)

    async def _on_reset(self) -> None:
        """IN4 triggered during input wait — reset to IDLE."""
        self._ticket_armed = False
        await self._transition(STATE_IDLE)
        await self._display()
        logger.info("gate_reset_by_sensor", gate_id=self.gate_id)

    async def _on_help_button(self) -> None:
        """IN4 help button — call the operator, never touch the transaction.

        The old version forced STATE_IDLE after 10s, which silently dropped a
        pending WAITING_INPUT/PROCESSING ticket if the driver pressed help
        while paying. Help must be informational only.
        """
        await self._cmd_play_audio(5)  # "Mohon tunggu"
        await self._display("Mohon Tunggu", "Petugas Membantu Anda")
        await self.publish_event(
            BaseEvent(event_type="help_button_pressed", gate_id=self.gate_id)
        )
        logger.info("help_button_called", gate_id=self.gate_id, state=self.state)

    async def _on_ticket_button_pressed(self) -> None:
        """Cash button pressed — notify API to create transaction and print."""
        await self._transition(STATE_PROCESSING)
        await self.publish_event(
            BaseEvent(event_type="ticket_button_pressed", gate_id=self.gate_id)
        )
        # PROCESSING is escapeless otherwise: the event is at-most-once
        # Pub/Sub, IN1/IN2/IN4 are ignored in this state, and nothing
        # publishes reset — a lost event would leave the gate dead until
        # `systemctl restart` while the heartbeat reports healthy.
        self._processing_task = self._spawn_tracked(
            self._processing_timeout(), name="processing_timeout"
        )

    async def _processing_timeout(self) -> None:
        timeout = (self.config.get("gate_open_timeout_s") or 10) * 3
        await asyncio.sleep(timeout)
        if self.state == STATE_PROCESSING:
            logger.warning("processing_timeout_reset", gate_id=self.gate_id)
            await self.publish_event(
                BaseEvent(event_type="processing_timeout", gate_id=self.gate_id)
            )
            await self._transition(STATE_IDLE)
            await self._display()

    async def _on_rfid_card_read(self, card_number: str, channel: str) -> None:
        """Wiegand card read — notify API to validate member."""
        await self._transition(STATE_VALIDATING)
        await self.publish_event(
            RfidCardReadEvent(
                event_type="rfid_card_read",
                gate_id=self.gate_id,
                card_number=card_number,
                channel=channel,
            )
        )
        self._validating_task = self._spawn_tracked(self._validating_timeout(), name="validating_timeout")

    async def _validating_timeout(self) -> None:
        timeout = self.config.get("gate_open_timeout_s") or 10
        await asyncio.sleep(timeout)
        if self.state == STATE_VALIDATING:
            logger.warning("validating_timeout_reset", gate_id=self.gate_id)
            await self._transition(STATE_IDLE)
            await self._display()

    async def _on_gate_opened(self) -> None:
        await self._transition(STATE_OPENING)
        await self.publish_event(
            BaseEvent(event_type="gate_opened", gate_id=self.gate_id)
        )
        self._spawn_tracked(self._vehicle_pass_timer(), name="vehicle_pass_timer")

    async def _vehicle_pass_timer(self) -> None:
        await asyncio.sleep(self.config.get("gate_open_timeout_s") or 10)
        if self.state == STATE_OPENING:
            await self._on_vehicle_passed()

    async def _on_vehicle_passed(self) -> None:
        self._ticket_armed = False
        await self._transition(STATE_IDLE)
        await self.publish_event(
            BaseEvent(event_type="vehicle_passed", gate_id=self.gate_id)
        )
        await self._display()
        await self._relay_close()
        self._loop_timer_done = False
        # Arm the lane for the next vehicle on a timer as well: some
        # controllers never emit IN3OFF, and waiting for it would leave the
        # loop latched. Skipped in IN3OFF-only mode.
        if self._lane_reset_mode != "in3off":
            self._schedule_loop_clear()
        else:
            self._maybe_clear_loop()

    def _schedule_loop_clear(self) -> None:
        self._spawn_tracked(self._clear_loop_after_delay(), name="loop_clear")

    async def _clear_loop_after_delay(self) -> None:
        await asyncio.sleep(self._lane_reset_seconds)
        self._loop_timer_done = True
        self._maybe_clear_loop()

    def _maybe_clear_loop(self) -> None:
        """Release the IN3 latch according to lane_reset_mode."""
        if not self._loop_occupied:
            return
        mode = self._lane_reset_mode
        release = (
            (mode == "time" and self._loop_timer_done)
            or (mode == "in3off" and self._loop_in3off)
            or (mode == "both" and self._loop_timer_done and self._loop_in3off)
        )
        if not release:
            return
        self._loop_occupied = False
        self._loop_timer_done = False
        self._loop_in3off = False
        logger.info(
            "loop_auto_cleared",
            gate_id=self.gate_id,
            seconds=self._lane_reset_seconds,
            mode=mode,
        )

    # ------------------------------------------------------------------
    # Command handlers (from Redis Streams)
    # ------------------------------------------------------------------

    async def handle_command(self, command_data: dict[str, str]) -> bool:
        command_type = command_data.get("command_type", "")
        logger.info("gate_in_command", gate_id=self.gate_id, command_type=command_type)
        try:
            if command_type == "open_gate":
                # Always ACK: a hard-down open is reported via the gate_open_failed
                # event + log, not by NACK. The command is only valid while the
                # vehicle waits (~seconds) — leaving it pending for later redelivery
                # would ghost-open the gate for the wrong vehicle. The bool still
                # gates the OPENING transition inside _cmd_open_gate.
                await self._cmd_open_gate()
            elif command_type == "close_gate":
                await self._relay_close()
            elif command_type == "brake_gate":
                await self._relay_brake()
            elif command_type == "play_audio":
                await self._cmd_play_audio(int(command_data.get("track", 1)))
            elif command_type == "display_text":
                await self._cmd_display_text(
                    command_data.get("line1", ""), command_data.get("line2", "")
                )
            elif command_type == "print_ticket_then_open":
                # Same ACK-and-report contract as open_gate (see above).
                await self._cmd_print_ticket_then_open(
                    command_data.get("barcode", ""),
                    command_data.get("gate_name", self.config.get("name", "")),
                )
            elif command_type == "reject_card":
                await self._cmd_reject_card(
                    command_data.get("line1", "Kartu Tidak Valid"),
                    command_data.get("line2", ""),
                    int(command_data.get("audio_track", 3)),
                    float(command_data.get("display_seconds", 3.0)),
                )
            elif command_type == "reset_gate":
                await self._cmd_reset_gate(command_data.get("reason", "operator"))
            elif command_type == "deduct":
                logger.warning("deduct_ignored_at_gate_in", gate_id=self.gate_id)
            else:
                logger.warning("unknown_command", gate_id=self.gate_id, command_type=command_type)
            return True
        except Exception as e:
            logger.error("command_error", gate_id=self.gate_id, command_type=command_type, error=str(e))
            return False

    async def _cmd_open_gate(self) -> bool:
        """Open the gate. Returns False if the relay never fired (after inline
        retry) so we never advance to OPENING on a failed open — the daemon must
        not believe a closed barrier is open. The failure is reported via the
        gate_open_failed event + log; the command is still ACKed (a stale open
        must not be redelivered later)."""
        if not await self._relay_open_reliable():
            logger.error("gate_open_failed_hard", gate_id=self.gate_id)
            await self.publish_event(BaseEvent(event_type="gate_open_failed", gate_id=self.gate_id))
            return False
        await self._cmd_play_audio(6)  # 6 = "Terima kasih"
        await self._on_gate_opened()
        return True

    async def _cmd_play_audio(self, track: int) -> None:
        track_map = self.hw.get("audio", {}).get("track_map", {})
        try:
            actual = int(track_map.get(str(track), track))
        except (TypeError, ValueError):
            # hardware_config is admin-editable JSON; a bad value must not
            # crash the state machine with a format-string TypeError.
            logger.warning("audio_track_map_invalid", gate_id=self.gate_id, track=track)
            actual = track
        if self.config.get("protocol", "compass") == "serial":
            await self.publish_event(PlayAudioEvent(gate_id=self.gate_id, track=actual))
        else:
            await self._send_controller_command(cmd_mt(f"{actual:05d}"))

    async def _cmd_display_text(self, line1: str, line2: str) -> None:
        await self._display(line1, line2)

    async def _cmd_print_ticket(self, barcode: str, gate_name: str) -> None:
        if not self.has_ticket_printer:
            logger.info("print_ticket_skipped_disabled", gate_id=self.gate_id, barcode=barcode)
            return
        logger.info("print_ticket_commanded", gate_id=self.gate_id, barcode=barcode)
        try:
            from shared.redis import get_arq_redis
            arq_redis = await get_arq_redis()
            await arq_redis.enqueue_job(
                "print_ticket",
                gate_id=self.gate_id,
                barcode=barcode,
                gate_name=gate_name,
                _job_id=f"print_ticket:{barcode}",
            )
        except Exception as e:
            logger.error("print_ticket_enqueue_failed", gate_id=self.gate_id, error=str(e))

    async def _cmd_print_ticket_then_open(self, barcode: str, gate_name: str) -> bool:
        """Print-first cash entry flow. Gate ALWAYS opens — never trap a vehicle.

        Returns the open result (for internal state only — the command is always
        ACKed). Print runs at most once per delivery (the command is not
        redelivered) — no double-print risk.
        """
        logger.info("print_ticket_then_open", gate_id=self.gate_id, barcode=barcode)
        audio_cfg = self.hw.get("audio", {})

        if not self.has_ticket_printer:
            logger.info("cash_ticket_print_skipped_disabled", gate_id=self.gate_id, barcode=barcode)
            if audio_cfg.get("enabled", True):
                await self._cmd_play_audio(audio_cfg.get("ticket_track", 2))  # 2 = "Silakan ambil tiket"
            return await self._cmd_open_gate()

        print_success = False
        printer_cfg = self.config.get("printer") or {}
        printer_mode = (printer_cfg.get("mode") or "AUTO").upper()
        if printer_mode == "AUTO":
            # Resolve per ticket: a swapped cable (network ↔ serial ↔ behind
            # controller) starts working without editing settings.
            import socket
            from pathlib import Path as _Path

            ip, port = printer_cfg.get("ip_address"), printer_cfg.get("port") or 9100
            serial_dev = printer_cfg.get("serial_device")
            printer_mode = "CONTROLLER_PASSTHROUGH"
            if ip:
                try:
                    with socket.create_connection((ip, int(port)), timeout=1.0):
                        printer_mode = "NETWORK"
                except OSError:
                    pass
            if printer_mode == "CONTROLLER_PASSTHROUGH" and serial_dev:
                try:
                    if str(serial_dev).startswith("/dev/usb/lp") and _Path(serial_dev).exists():
                        printer_mode = "USB"
                    elif _Path(serial_dev).exists():
                        printer_mode = "SERIAL"
                except OSError:
                    pass
            logger.info("printer_mode_auto_resolved", gate_id=self.gate_id, mode=printer_mode)
        try:
            if printer_mode in ("NETWORK", "SERIAL", "USB"):
                # The physical printer is not behind the controller. Only the
                # print worker knows how to talk to it (python-escpos / serial),
                # so hand the job over instead of sending PR3 into the PCLess.
                await self._cmd_print_ticket(barcode, gate_name)
                await asyncio.sleep(2.0)
                print_success = True
                logger.info(
                    "cash_ticket_handed_to_worker",
                    gate_id=self.gate_id,
                    barcode=barcode,
                    printer_mode=printer_mode,
                )
            else:
                # Single source of truth for the ticket layout (centering
                # without ESC a, ESC @ init, barcode, footer).
                from workers.critical.print_worker import _build_escpos_ticket

                site = self.config.get("site_name") or ""
                escpos_data = _build_escpos_ticket(
                    barcode=barcode,
                    gate_name=gate_name,
                    location_name=site,
                )
                await self._send_controller_command(cmd_pr3(escpos_data))
                await asyncio.sleep(1.5)
                print_success = True
                logger.info("cash_ticket_printed", gate_id=self.gate_id, barcode=barcode)
        except Exception as e:
            logger.error("cash_ticket_print_failed", gate_id=self.gate_id, barcode=barcode, error=str(e))

        if not print_success:
            await self._send_controller_command(cmd_ds("CATAT NOMOR:", barcode))
            await self.publish_event(BaseEvent(event_type="print_failed_alert", gate_id=self.gate_id))
            await asyncio.sleep(3)
            if audio_cfg.get("enabled", True):
                await self._cmd_play_audio(audio_cfg.get("error_track", 11))
        else:
            if audio_cfg.get("enabled", True):
                await self._cmd_play_audio(audio_cfg.get("ticket_track", 2))  # 2 = "Silakan ambil tiket"

        return await self._cmd_open_gate()

    async def _cmd_reject_card(self, line1: str, line2: str, audio_track: int, display_seconds: float) -> None:
        """Show rejection message then return to WAITING_INPUT — driver can retry immediately."""
        if self._validating_task and not self._validating_task.done():
            self._validating_task.cancel()
        await self._display(line1, line2)
        await self._cmd_play_audio(audio_track)
        await asyncio.sleep(display_seconds)
        await self._transition(STATE_WAITING_INPUT)
        await self._display("Selamat Datang", "Tombol/Tempel Kartu")

    async def _cmd_reset_gate(self, reason: str) -> None:
        logger.info("reset_gate", gate_id=self.gate_id, reason=reason)
        await self._transition(STATE_IDLE)
        await self._display()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _rfid_serial_reader_task(self) -> None:
        """Read card numbers from a directly-connected serial RFID reader.

        The device may be absent at boot (USB not enumerated yet) or disappear
        mid-run; retry with capped backoff instead of giving up permanently.
        """
        rfid_cfg = self.hw.get("rfid", {})
        device = rfid_cfg.get("device")
        baudrate = rfid_cfg.get("baudrate", 9600)
        if not device:
            logger.error("rfid_serial_no_device", gate_id=self.gate_id)
            return

        loop = asyncio.get_event_loop()
        delay = 1.0
        while self._running:
            ser = None
            try:
                import serial as _serial
                ser = _serial.Serial(port=device, baudrate=baudrate, timeout=0.5)
                delay = 1.0
                logger.info("rfid_serial_reader_started", gate_id=self.gate_id, device=device)
                while self._running:
                    raw = await loop.run_in_executor(None, ser.readline)
                    card_number = raw.decode("ascii", errors="ignore").strip()
                    if card_number and self.has_rfid:
                        vehicle_present = self._in1_on
                        if vehicle_present and self.state == STATE_WAITING_INPUT:
                            await self._on_rfid_card_read(card_number, "S")
                        elif not vehicle_present:
                            logger.info(
                                "rfid_serial_ignored_no_vehicle",
                                gate_id=self.gate_id,
                                card=card_number,
                            )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "rfid_serial_reader_error",
                    gate_id=self.gate_id,
                    error=str(e),
                    next_retry_s=delay,
                )
                if ser is not None:
                    with contextlib.suppress(Exception):
                        ser.close()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
            finally:
                if ser is not None:
                    with contextlib.suppress(Exception):
                        ser.close()

    async def _send_controller_command(self, command: bytes) -> bool:
        """Send a framed command to the controller.

        Returns True if the write landed on the socket, False if the command was
        dropped (controller down or circuit breaker open). Best-effort callers
        ignore the result; the critical gate-open path uses it to retry/NACK.
        """
        controller = self.controller
        if not (controller and controller.is_connected()):
            return False

        # Circuit breaker open? Fast-fail without grabbing the lock.
        loop = asyncio.get_event_loop()
        now = loop.time()
        if now < self._cb_open_until:
            logger.warning(
                "controller_cb_open_skip",
                gate_id=self.gate_id,
                reopen_in_s=round(self._cb_open_until - now, 2),
            )
            return False

        try:
            # Executor: a stalled controller may hold sendall for SEND_TIMEOUT_S;
            # that must not freeze RSS, heartbeat and the Redis consumer.
            async with self._controller_lock:
                await loop.run_in_executor(None, controller.send, command)
            logger.debug("controller_cmd_sent", gate_id=self.gate_id, cmd=command.hex())
            if self._cb_fail_count:
                logger.info("controller_cb_reset", gate_id=self.gate_id)
            self._cb_fail_count = 0
            return True
        except Exception as e:
            if self.controller is not controller:
                # Link was swapped while this send waited (RSS listener already
                # reconnected). Never abort or penalise the fresh link.
                logger.debug("controller_cmd_stale_link", gate_id=self.gate_id, error=str(e))
                return False
            self._cb_fail_count += 1
            logger.error(
                "controller_cmd_error",
                gate_id=self.gate_id,
                error=str(e),
                fail_count=self._cb_fail_count,
            )
            # A write failure means the socket is dead on the TX side. recv() may
            # never see EOF if no data is pending, so the listener would keep the
            # half-open socket. Tear it down here so is_connected() flips False and
            # the RSS listener reconnects within one poll cycle.
            controller.last_error = f"send failed: {e}"
            controller.abort()
            if self._cb_fail_count >= self._cb_threshold:
                self._cb_open_until = now + self._cb_cooldown_s
                logger.warning(
                    "controller_cb_open",
                    gate_id=self.gate_id,
                    cooldown_s=self._cb_cooldown_s,
                )
            return False
