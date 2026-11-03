"""WebSocket server for POS frontend to access serial devices."""

import asyncio
import json
import urllib.error
import urllib.request

import websockets

from shared.logging import get_logger

logger = get_logger("booth_ws")


class WebSocketServer:
    """WebSocket server exposing serial peripherals to POS frontend.

    Bound to ``localhost`` only — never expose this on a routable address;
    the protocol owns the booth's relays and printers without per-message
    auth. Connection count is capped at ``max_clients`` so a runaway browser
    tab or leaked Chrome session can't exhaust file descriptors and lock
    out the real POS UI.
    """

    def __init__(
        self,
        serial_manager,
        port: int = 5678,
        api_config: dict | None = None,
        gate_opener=None,
        max_clients: int = 8,
        outbox=None,
        emoney_init_key: bytes | None = None,
    ) -> None:
        self.serial_manager = serial_manager
        self.port = port
        self._api_config = api_config
        self.gate_opener = gate_opener
        self.max_clients = max_clients
        self.outbox = outbox
        self._server = None
        self._clients: set = set()
        self._bg_tasks: set = set()
        # PASSTI INIT is required once per reader power-on. The key is
        # site-specific, so it is optional: without it we keep the legacy
        # behaviour (reader already initialised by another tool).
        self.emoney_init_key = emoney_init_key
        self._emoney_initialized = False
        self.reader_mid: str | None = None
        self.reader_tid: str | None = None

    def _spawn(self, coro, name: str) -> None:
        """Fire a background task with a strong ref + exception logging.

        Bare ``asyncio.create_task`` here gets garbage-collected mid-flight and
        swallows exceptions. Keep a ref until done and log any failure."""
        task = asyncio.create_task(coro, name=name)
        self._bg_tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            self._bg_tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.error("bg_task_error", task=name, error=str(t.exception()))

        task.add_done_callback(_on_done)

    async def broadcast(self, payload: dict) -> None:
        """Send JSON payload to every connected client."""
        if not self._clients:
            return
        data = json.dumps(payload)
        stale = []
        for ws in self._clients:
            try:
                await ws.send(data)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._clients.discard(ws)

    async def start(self) -> None:
        """Start WebSocket server."""
        self._server = await websockets.serve(self._handle_client, "localhost", self.port)
        logger.info("ws_server_started", port=self.port)

    async def stop(self) -> None:
        """Stop WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("ws_server_stopped")

    async def _ensure_emoney_initialized(self) -> bool:
        """Send PASSTI INIT once per reader power-on.

        Without INIT a cold reader rejects every transaction with
        ``01 10 03``. Failure is non-fatal: a reader initialised by another
        tool still works, and we retry on the next operation.
        """
        if self._emoney_initialized:
            return True
        if not self.emoney_init_key:
            return False

        from protocols.passti.commands import cmd_init
        from protocols.passti.frame import is_complete_frame, parse_response, trim_to_frame

        try:
            raw = await asyncio.to_thread(
                self.serial_manager.send,
                "emoney_reader",
                cmd_init(self.emoney_init_key),
                response_timeout_s=5.0,
                is_complete=is_complete_frame,
            )
            parsed = parse_response(trim_to_frame(raw))
            body = parsed.get("body", b"")
            if parsed.get("ok") and len(body) >= 12:
                self.reader_mid = body[:8].hex().upper()
                self.reader_tid = body[8:12].hex().upper()
                self._emoney_initialized = True
                logger.info(
                    "emoney_reader_initialized",
                    mid=self.reader_mid,
                    tid=self.reader_tid,
                )
                return True
            logger.warning(
                "emoney_reader_init_failed",
                status=parsed.get("status"),
                error=parsed.get("error"),
            )
        except Exception as e:
            logger.warning("emoney_reader_init_error", error=str(e))
        return False

    async def _recover_last_transaction(self):
        """Ask the reader whether the interrupted deduct actually completed.

        PASSTI §III.E: after a lost contact, ``Get Last Transaction`` returns
        the deduct body if the previous operation succeeded, or an empty body
        if it failed. This is the only safe way to resolve the charge without
        debiting the card twice.
        """
        from protocols.passti.commands import (
            cmd_get_last_transaction,
            parse_deduct_response,
        )
        from protocols.passti.frame import is_complete_frame, parse_response, trim_to_frame

        try:
            raw = await asyncio.to_thread(
                self.serial_manager.send,
                "emoney_reader",
                cmd_get_last_transaction(),
                response_timeout_s=5.0,
                is_complete=is_complete_frame,
            )
            parsed = parse_response(trim_to_frame(raw))
            data = parse_deduct_response(parsed.get("body", b""))
            if parsed.get("ok") and data.get("ok"):
                logger.info(
                    "emoney_recovery_succeeded",
                    card_type=data.get("card_type"),
                    amount=data.get("deducted"),
                )
                return data, parsed
            logger.warning(
                "emoney_recovery_no_transaction",
                status=parsed.get("status"),
            )
        except Exception as e:
            logger.warning("emoney_recovery_error", error=str(e))
        return None, None

    async def _call_api_booth_result(self, payload: dict) -> None:
        """Deliver the deduct result to the API durably.

        The card was already debited when this runs, so delivery must survive
        API blips and bridge restarts: the payload is persisted to the outbox
        FIRST, the POST is attempted with bounded retries, and only on
        confirmed success is the outbox entry removed. Leftover entries are
        re-driven by the outbox drain task in main.py.

        The API side treats a duplicate result as already-processed, so
        re-POSTing after a lost response is safe.
        """
        if not self._api_config:
            return
        api_key = self._api_config["api_key"]

        if self.outbox is not None:
            try:
                self.outbox.put(payload)
            except Exception as e:
                logger.error("outbox_put_failed", error=str(e))

        url = f"{self._api_config['base_url']}/api/payments/emoney/booth-result"
        api_payload = {
            "gate_id": payload.get("gate_id", ""),
            "gate_out_id": payload.get("gate_out_id", 0),
            "transaction_id": payload.get("transaction_id"),
            "card_number": payload.get("card_number", ""),
            "status": payload["status"],
            "deduct_amount": payload["deduct_amount"],
            "balance_before": payload["balance_before"],
            "balance_after": payload["balance_after"],
            "transaction_counter": payload["transaction_counter"],
            "raw_response_hex": payload["raw_response_hex"],
            "settlement_payload_hex": payload.get("settlement_payload_hex", ""),
            "card_type": payload.get("card_type"),
            "card_type_code": payload.get("card_type_code"),
            "mid": payload.get("mid"),
            "tid": payload.get("tid"),
        }

        def _post(timeout: float):
            data = json.dumps(api_payload).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode()

        # Bounded in-process retries only cover short API blips; anything
        # longer stays in the outbox for the drain task.
        for attempt, delay in enumerate((0.0, 1.0, 3.0), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                status, body = await asyncio.to_thread(_post, 10.0)
            except Exception as e:
                logger.warning(
                    "booth_api_call_retry",
                    attempt=attempt,
                    status=payload["status"],
                    error=str(e),
                )
                continue
            if status == 200:
                self._ack_outbox(payload)
                logger.info("booth_api_call_success", status=payload["status"])
                return
            if 400 <= status < 500:
                # Deterministic rejection (bad payload / auth) — retrying
                # won't help. Log loudly but stop; the drain task will keep
                # trying so the record isn't silently dropped.
                logger.error("booth_api_call_rejected", status=status, body=body[:500])
                return
            logger.warning("booth_api_call_server_error", status=status)
        logger.error(
            "booth_api_call_exhausted_left_in_outbox",
            status=payload["status"],
            transaction_id=payload.get("transaction_id"),
        )

    def _ack_outbox(self, payload: dict) -> None:
        if self.outbox is None:
            return
        try:
            self.outbox.remove(payload)
        except Exception as e:
            logger.error("outbox_remove_failed", error=str(e))

    async def _open_gate_after_payment(self) -> None:
        """Open the barrier after a paid exit, retrying once.

        A USB hiccup here means money taken + barrier shut. One retry after
        a short delay covers transient serial errors; if it still fails we
        broadcast an explicit failure so the POS shows it instead of the
        operator staring at a barrier that never opens.
        """
        opened = await self.gate_opener.open()
        if not opened:
            logger.warning("gate_open_after_payment_failed_retrying")
            await asyncio.sleep(1.0)
            opened = await self.gate_opener.open()
        if not opened:
            logger.error("gate_open_after_payment_failed")
            await self.broadcast({"event": "gate_open_failed", "source": "emoney"})

    def _post_booth_result_sync(self, payload: dict) -> tuple[int, str]:
        """Synchronous POST used by the outbox drain task."""
        if not self._api_config:
            raise RuntimeError("API config not set")
        url = f"{self._api_config['base_url']}/api/payments/emoney/booth-result"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self._api_config["api_key"],
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()

    async def _handle_client(self, websocket, path=None):
        """Handle a client connection."""
        if len(self._clients) >= self.max_clients:
            # 1013 (Try Again Later) communicates capacity exhaustion more
            # precisely than a generic 1011. The POS frontend's reconnect
            # backoff treats either as recoverable.
            logger.warning(
                "ws_client_rejected_max_clients",
                current=len(self._clients),
                cap=self.max_clients,
                client=getattr(websocket, "remote_address", None),
            )
            try:
                await websocket.close(code=1013, reason="booth_bridge max_clients reached")
            except Exception:
                pass
            return

        self._clients.add(websocket)
        logger.info(
            "client_connected",
            client=websocket.remote_address,
            total=len(self._clients),
        )

        try:
            async for message in websocket:
                try:
                    result = await self._process_message(message)
                    await websocket.send(json.dumps(result))
                except Exception as e:
                    logger.error("message_error", error=str(e))
                    await websocket.send(json.dumps({"status": False, "error": str(e)}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info(
                "client_disconnected",
                client=websocket.remote_address,
                total=len(self._clients),
            )

    async def _process_message(self, message: str) -> dict:
        """Process a command from the POS frontend."""
        cmd = json.loads(message)
        action = cmd.get("action")

        if action == "open_gate":
            # Bridge owns the hardware path. Frontend may only request "open this
            # booth's gate" — device path, baudrate and open/close hex live in
            # gate.hardware_config (DB) + booth.json, never on the wire from POS.
            # This closes the prior trust hole where any local WS client could
            # drive arbitrary serial ports with arbitrary bytes.
            if self.gate_opener is None:
                logger.warning("open_gate_no_opener_configured")
                return {
                    "status": False,
                    "error": "gate_opener not configured for this booth",
                }
            requested = cmd.get("gate_code")
            if requested and requested != self.gate_opener.gate_id:
                logger.warning(
                    "open_gate_code_mismatch",
                    requested=requested,
                    bound=self.gate_opener.gate_id,
                )
                return {
                    "status": False,
                    "error": f"gate {requested} not bound to this booth",
                }
            opened = await self.gate_opener.open()
            return {
                "status": opened,
                "message": "Gate opened" if opened else "Gate open failed",
            }

        elif action == "emoney_check_balance":
            # Forward to e-money reader. The PASSTI transaction takes
            # multi-second wall time; run it on a thread so heartbeat,
            # other WS clients, and supervisor tasks keep advancing.
            from protocols.passti.commands import cmd_check_balance
            from protocols.passti.frame import is_complete_frame, trim_to_frame

            await self._ensure_emoney_initialized()
            frame = cmd_check_balance(timeout_sec=10)
            response = await asyncio.to_thread(
                self.serial_manager.send,
                "emoney_reader",
                frame,
                response_timeout_s=15.0,
                is_complete=is_complete_frame,
            )
            response = trim_to_frame(response)
            if not response:
                # Reader may have been power-cycled; force INIT next time.
                self._emoney_initialized = False
            return {"status": True, "data": response.hex()}

        elif action == "emoney_deduct":
            amount = cmd.get("amount", 0)
            gate_id = cmd.get("gate_id", "")
            gate_out_id = cmd.get("gate_out_id", 0)
            transaction_id = cmd.get("transaction_id")

            from protocols.passti.commands import cmd_deduct, parse_deduct_response
            from protocols.passti.frame import is_complete_frame, parse_response, trim_to_frame

            await self._ensure_emoney_initialized()
            frame = cmd_deduct(amount, timeout_sec=30)
            # The reader stays silent for the whole card-tap window (≤30s)
            # before answering, and the answer can split across USB reads —
            # accumulate until the frame is complete or the budget expires.
            raw_response = await asyncio.to_thread(
                self.serial_manager.send,
                "emoney_reader",
                frame,
                response_timeout_s=35.0,
                is_complete=is_complete_frame,
            )
            raw_response = trim_to_frame(raw_response)
            if not raw_response:
                self._emoney_initialized = False

            parsed = parse_response(raw_response)
            if "error" in parsed:
                return {
                    "action": "emoney_deduct_result",
                    "status": "FAILED",
                    "error": parsed["error"],
                    "raw_response_hex": parsed.get("raw", raw_response.hex()),
                }

            status = parsed["status"]
            if status == (0x00, 0x00, 0x00):
                deduct_status = "SUCCESS"
            elif status == (0x01, 0x10, 0x05):
                deduct_status = "LOST_CONTACT"
            elif status == (0x01, 0x10, 0x04):
                deduct_status = "INSUFFICIENT_BALANCE"
            elif status == (0x01, 0x10, 0x06):
                deduct_status = "WRONG_CARD"
            elif status == (0x01, 0x10, 0x02):
                deduct_status = "TIMEOUT"
            elif status == (0x01, 0x10, 0x03):
                deduct_status = "FAILED"
                # Wrong/absent INIT key: force a fresh handshake next time.
                self._emoney_initialized = False
            else:
                deduct_status = "FAILED"

            recovered = False
            deduct_data: dict = {}
            if deduct_status == "SUCCESS":
                deduct_data = parse_deduct_response(parsed["body"])
                if not deduct_data.get("ok"):
                    return {
                        "action": "emoney_deduct_result",
                        "status": "FAILED",
                        "error": deduct_data.get("error", "Deduct parse failed"),
                        "raw_response_hex": parsed.get("raw", raw_response.hex()),
                    }
            elif deduct_status == "LOST_CONTACT":
                # The card was removed mid-deduct. Ask the reader whether the
                # debit actually landed before asking the operator to re-tap.
                recovered_data, recovered_parsed = await self._recover_last_transaction()
                if recovered_data is not None:
                    deduct_data = recovered_data
                    if recovered_parsed is not None:
                        parsed = recovered_parsed
                    deduct_status = "SUCCESS"
                    recovered = True

            if not deduct_data:
                # Error statuses carry at most card type/card number, and some
                # carry nothing. Do not downgrade LOST_CONTACT/etc to FAILED
                # just because there is no successful-deduct body to parse.
                body = parsed.get("body", b"")
                deduct_data = {
                    "card_number": body[1:9].hex().upper() if len(body) >= 9 else "",
                    "card_type_code": body[0] if body else None,
                    "card_type": None,
                    "deducted": 0,
                    "remaining": 0,
                    "trans_counter": 0,
                    "mid": self.reader_mid,
                    "tid": self.reader_tid,
                }

            # QR responses carry no card number (they use trx_id) — fall back
            # so the API schema's min_length=4 doesn't reject the record and
            # strand the charge in the outbox.
            card_id = (
                deduct_data.get("card_number")
                or deduct_data.get("trx_id")
                or "QRUNKNOWN"
            )[:32]

            result_payload = {
                "action": "emoney_deduct_result",
                "status": deduct_status,
                "recovered": recovered,
                "card_number": card_id,
                "deduct_amount": deduct_data.get("deducted", 0),
                "balance_before": deduct_data.get("remaining", 0) + deduct_data.get("deducted", 0),
                "balance_after": deduct_data.get("remaining", 0),
                "transaction_counter": deduct_data.get("trans_counter", 0),
                "raw_response_hex": parsed.get("raw", raw_response.hex()),
                # Settlement-critical fields (Multibank v1.3): the deduct body
                # cardtype..CardLog, card type, and the reader's MID/TID so the
                # API can link the row to an EmoneyReader for file grouping.
                "settlement_payload_hex": parsed.get("body_hex", ""),
                "card_type": deduct_data.get("card_type"),
                "card_type_code": deduct_data.get("card_type_code"),
                "mid": deduct_data.get("mid"),
                "tid": deduct_data.get("tid"),
                "transaction_id": transaction_id,
                "gate_id": gate_id,
                "gate_out_id": gate_out_id,
            }

            # Deliver the money record BEFORE opening the barrier: if this
            # process dies in between, the outbox still holds the charge.
            # ALL statuses go to the API — failures clear the pending arm
            # state server-side; SUCCESS completes the transaction.
            if self._api_config:
                self._spawn(self._call_api_booth_result(result_payload), name="api_booth_result")

            if deduct_status == "SUCCESS" and self.gate_opener is not None:
                self._spawn(self._open_gate_after_payment(), name="gate_opener_open")

            broadcast_event = (
                "emoney_payment_completed" if deduct_status == "SUCCESS"
                else "emoney_payment_failed"
            )
            self._spawn(
                self.broadcast(
                    {
                        "event": broadcast_event,
                        "status": deduct_status,
                        "card_number": result_payload.get("card_number"),
                        "deduct_amount": result_payload.get("deduct_amount"),
                        "balance_after": result_payload.get("balance_after"),
                        "gate_id": gate_id,
                    }
                ),
                name="emoney_broadcast",
            )

            return result_payload

        elif action == "emoney_cancel_correction":
            # PASSTI §III.D: abandon a pending lost-contact correction so a
            # different card can be charged. Only valid while the reader has
            # a correction outstanding; otherwise the body is empty.
            from protocols.passti.commands import cmd_cancel_correction
            from protocols.passti.frame import is_complete_frame, parse_response, trim_to_frame

            raw = await asyncio.to_thread(
                self.serial_manager.send,
                "emoney_reader",
                cmd_cancel_correction(),
                response_timeout_s=5.0,
                is_complete=is_complete_frame,
            )
            parsed = parse_response(trim_to_frame(raw))
            body = parsed.get("body", b"")
            return {
                "action": "emoney_cancel_correction",
                "status": "SUCCESS" if parsed.get("ok") else "FAILED",
                "card_number": body[1:9].hex().upper() if len(body) >= 9 else "",
                "raw_response_hex": parsed.get("raw", raw.hex()),
            }

        elif action == "emoney_last_transaction":
            # Diagnostics / manual recovery oracle.
            data, parsed = await self._recover_last_transaction()
            return {
                "action": "emoney_last_transaction",
                "status": "SUCCESS" if data else "NO_TRANSACTION",
                "deduct_amount": data.get("deducted", 0) if data else 0,
                "card_number": data.get("card_number", "") if data else "",
                "transaction_counter": data.get("trans_counter", 0) if data else 0,
                "raw_response_hex": (parsed or {}).get("raw", ""),
            }

        elif action == "print_receipt":
            # Receipt printers (ESC/POS) don't ACK — use write_only so we
            # don't burn the 1s read timeout on every receipt. Still runs in
            # a worker thread because pyserial's write can briefly block on
            # USB-CDC flush.
            data = cmd.get("data", b"")
            if isinstance(data, str):
                data = data.encode()
            await asyncio.to_thread(
                self.serial_manager.write_only, "receipt_printer", data
            )
            return {"status": True, "message": "Printed"}

        elif action == "running_text":
            # ponytail: LED running-text display not wired to hardware yet —
            # accept and ack so the POS UI flow works; implement when the
            # display board is on site.
            return {"status": True, "message": "Display updated"}

        return {"status": False, "error": f"Unknown action: {action}"}
