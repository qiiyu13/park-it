"""Evdev keyboard-wedge poller for booth exit RFID (Omnikey 5427 CK).

Omnikey 5427 CK in HID keyboard mode types the card UID as ASCII digits
into the focused window. Some firmware configurations omit the trailing
Enter, so we flush the digit buffer when either Enter is seen OR no
digit arrives within `flush_idle_ms` after the last digit.

We grab the keyboard event device exclusively to avoid the digits
leaking into the desktop's focused window.

Requirements:
    - python-evdev installed in the venv
    - process can read /dev/input/eventX (input group OR udev rule OR
      `setfacl -m u:<user>:rw /dev/input/eventXX`)
"""

from __future__ import annotations

import asyncio
import glob
import time
from collections.abc import Awaitable, Callable
from typing import Any

from shared.logging import get_logger

logger = get_logger("booth_omnikey")

_DIGIT_KEYS = {
    "KEY_0": "0", "KEY_1": "1", "KEY_2": "2", "KEY_3": "3", "KEY_4": "4",
    "KEY_5": "5", "KEY_6": "6", "KEY_7": "7", "KEY_8": "8", "KEY_9": "9",
    "KEY_KP0": "0", "KEY_KP1": "1", "KEY_KP2": "2", "KEY_KP3": "3", "KEY_KP4": "4",
    "KEY_KP5": "5", "KEY_KP6": "6", "KEY_KP7": "7", "KEY_KP8": "8", "KEY_KP9": "9",
}
_ENTER_KEYS = {"KEY_ENTER", "KEY_KPENTER"}


class OmnikeyPoller:
    def __init__(
        self,
        gate_id: str,
        gate_db_id: int,
        api_client,
        gate_opener,
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        device_path: str | None = None,
        device_name_match: str = "omnikey",
        dedupe_cooldown_s: float = 3.0,
        flush_idle_ms: int = 200,
        min_card_len: int = 6,
        # Below this length the buffer is treated as stray keystrokes and
        # silently dropped (no toast). Between this and ``min_card_len`` we
        # *do* emit an invalid-card event so the operator gets feedback when
        # a real but malformed read happens (worn card, reader glitch).
        min_invalid_feedback_len: int = 3,
    ) -> None:
        self.gate_id = gate_id
        self.gate_db_id = gate_db_id
        self.api = api_client
        self.opener = gate_opener
        self.broadcast = broadcast
        self.device_path = device_path
        self.device_name_match = device_name_match.lower()
        self.dedupe_cooldown_s = dedupe_cooldown_s
        self.flush_idle_s = flush_idle_ms / 1000.0
        self.min_card_len = min_card_len
        self.min_invalid_feedback_len = min_invalid_feedback_len
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_card: str | None = None
        self._last_card_at: float = 0.0
        self._event_queue: asyncio.Queue | None = None
        self.connected: bool = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"omnikey_poll_{self.gate_id}")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def _find_device(self):
        from evdev import InputDevice, list_devices

        if self.device_path:
            try:
                return InputDevice(self.device_path)
            except Exception as e:
                logger.warning("omnikey_open_path_failed", path=self.device_path, error=str(e))
                return None

        for path in list_devices():
            try:
                dev = InputDevice(path)
                if self.device_name_match in dev.name.lower():
                    return dev
            except Exception:
                continue

        for path in glob.glob("/dev/input/by-id/*omnikey*event-kbd") + \
                    glob.glob("/dev/input/by-id/*OMNIKEY*event-kbd"):
            try:
                return InputDevice(path)
            except Exception:
                continue
        return None

    async def _run(self) -> None:
        from evdev import KeyEvent, categorize, ecodes

        loop = asyncio.get_event_loop()

        # Escalating backoff for the find/grab loop. Default 3s for the first
        # few attempts so a hot-plug recovers fast; doubles up to 30s if the
        # condition persists. Every ``_loud_every`` attempts the log level
        # bumps to WARNING with attempt count + recommended remediation, so
        # ops notices a stuck reader instead of seeing a single info line.
        attempts = 0
        backoff_s = 3.0
        backoff_cap_s = 30.0
        loud_every = 5

        def _backoff_log(event: str, **fields) -> None:
            level = "warning" if attempts and attempts % loud_every == 0 else "info"
            getattr(logger, level)(
                event,
                attempts=attempts,
                next_sleep_s=backoff_s,
                **fields,
            )

        while self._running:
            dev = await loop.run_in_executor(None, self._find_device)
            if dev is None:
                attempts += 1
                self.connected = False
                _backoff_log(
                    "omnikey_device_not_found",
                    match=self.device_name_match,
                    hint=(
                        "Reader unplugged or kernel hasn't enumerated it. "
                        "Check `ls /dev/input/by-id/ | grep -i omnikey`."
                    ) if attempts % loud_every == 0 else None,
                )
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, backoff_cap_s)
                continue

            try:
                dev.grab()
            except Exception as e:
                attempts += 1
                self.connected = False
                _backoff_log(
                    "omnikey_grab_failed",
                    device=dev.path,
                    error=str(e),
                    hint=(
                        "Another process holds the device exclusively. "
                        "Check `sudo fuser /dev/input/eventXX` or stop "
                        "evtest / a stray bridge."
                    ) if attempts % loud_every == 0 else None,
                )
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, backoff_cap_s)
                continue

            # Reset backoff after a successful grab — the device is healthy
            # again. Any later disconnect re-enters the loop and starts over
            # from 3s, so a brief hiccup doesn't carry penalty forward.
            if attempts > 0:
                logger.info(
                    "omnikey_recovered_after_failures",
                    attempts=attempts,
                    device=dev.path,
                )
            attempts = 0
            backoff_s = 3.0
            self.connected = True
            logger.info("omnikey_device_opened", device=dev.path, name=dev.name, gate_id=self.gate_id)

            queue: asyncio.Queue = asyncio.Queue()

            def _on_readable(dev=dev, queue=queue):
                try:
                    for ev in dev.read():
                        queue.put_nowait(ev)
                except BlockingIOError:
                    pass
                except OSError as e:
                    queue.put_nowait(e)

            loop.add_reader(dev.fd, _on_readable)

            buffer: list[str] = []
            last_digit_at: float | None = None

            try:
                while self._running:
                    timeout = None
                    if buffer and last_digit_at is not None:
                        elapsed = time.monotonic() - last_digit_at
                        timeout = max(0.0, self.flush_idle_s - elapsed)

                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=timeout)
                    except TimeoutError:
                        if buffer:
                            await self._flush_buffer(buffer)
                            buffer = []
                            last_digit_at = None
                        continue

                    if isinstance(event, OSError):
                        raise event
                    if event.type != ecodes.EV_KEY:
                        continue
                    key_event = categorize(event)
                    if key_event.keystate != KeyEvent.key_down:
                        continue
                    keycode = key_event.keycode
                    if isinstance(keycode, list):
                        keycode = keycode[0]
                    if keycode in _DIGIT_KEYS:
                        buffer.append(_DIGIT_KEYS[keycode])
                        last_digit_at = time.monotonic()
                    elif keycode in _ENTER_KEYS and buffer:
                        await self._flush_buffer(buffer)
                        buffer = []
                        last_digit_at = None
            except OSError as e:
                logger.warning("omnikey_device_disconnected", error=str(e))
            except Exception as e:
                logger.error("omnikey_loop_error", error=str(e))
            finally:
                self.connected = False
                try:
                    loop.remove_reader(dev.fd)
                except Exception:
                    pass
                try:
                    dev.ungrab()
                except Exception:
                    pass
                try:
                    dev.close()
                except Exception:
                    pass

            await asyncio.sleep(2)

    async def _flush_buffer(self, buffer: list[str]) -> None:
        if len(buffer) < self.min_card_len:
            # Emit a visible reject event for buffers long enough to look like
            # a real (but malformed) card read — too few digits = stray
            # keystrokes, drop silently. Operator gets a toast instead of
            # wondering why the tap did nothing.
            if len(buffer) >= self.min_invalid_feedback_len:
                partial = "".join(buffer)
                logger.warning(
                    "omnikey_card_too_short",
                    partial=partial,
                    digits=len(buffer),
                    min=self.min_card_len,
                    gate_id=self.gate_id,
                )
                await self.broadcast(
                    {
                        "event": "member_card_scanned",
                        "gate_id": self.gate_id,
                        "card_number": partial,
                        "success": False,
                        "message": (
                            f"Kartu tidak terbaca penuh ({len(buffer)} digit) — "
                            "coba tap ulang."
                        ),
                        "reason": "card_too_short",
                        "transaction_id": None,
                    }
                )
            return
        card_number = "".join(buffer)
        await self._handle_card(card_number)

    async def _handle_card(self, card_number: str) -> None:
        now = asyncio.get_event_loop().time()
        if (
            card_number == self._last_card
            and (now - self._last_card_at) < self.dedupe_cooldown_s
        ):
            return
        self._last_card = card_number
        self._last_card_at = now

        logger.info("omnikey_card_read", card=card_number, gate_id=self.gate_id)

        result = await self.api.rfid_exit(self.gate_id, self.gate_db_id, card_number)
        success = bool(result.get("success"))

        await self.broadcast(
            {
                "event": "member_card_scanned",
                "gate_id": self.gate_id,
                "card_number": card_number,
                "success": success,
                "message": result.get("message", ""),
                "reason": None if success else (result.get("reason") or "api_rejected"),
                "transaction_id": result.get("transaction_id"),
            }
        )

        if success:
            opened = await self.opener.open()
            if not opened:
                logger.error("omnikey_open_relay_failed", card=card_number, gate_id=self.gate_id)
        else:
            logger.warning(
                "omnikey_member_rejected",
                card=card_number,
                gate_id=self.gate_id,
                reason=result.get("message"),
            )
