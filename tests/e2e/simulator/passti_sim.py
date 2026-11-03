"""PASSTI e-money reader TCP simulator.

Simulates PASSTI reader frame protocol:
- Accepts: INIT, CheckBalance, Deduct, CancelDeduct, GetLastTransaction
- Returns configurable responses: SUCCESS, LOST_CONTACT, INSUFFICIENT_BALANCE, etc.
"""

import asyncio

from protocols.passti.frame import build_response
from shared.logging import get_logger

# structlog, not stdlib logging — see the note in controller_sim.py: the call
# sites pass keyword context that stdlib Logger.info raises TypeError on.
logger = get_logger("passti_sim")


class PasstiSimulator:
    """PASSTI reader TCP simulator."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self.server: asyncio.Server | None = None
        self._next_status = "SUCCESS"
        self._card_type = 0x02  # Mandiri eMoney
        # Wire fields are raw bytes; these are their hex representations.
        self._mid = "02034567890ABCDE"  # 8 bytes
        self._tid = "87654321"  # 4 bytes
        self._card_number = "5712017101900004"  # 8 bytes
        self._transaction_counter = 1
        self._command_log: list[bytes] = []

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        self.port = self.server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        logger.info("passti_sim_started", host=self.host, port=self.port)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("passti_sim_stopped")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        addr = writer.get_extra_info("peername")
        logger.info("passti_sim_client_connected", addr=addr)
        try:
            buffer = b""
            while True:
                chunk = await reader.read(1024)
                if not chunk:
                    break
                buffer += chunk

                # Parse frames from buffer
                while b"\x02" in buffer:
                    stx_idx = buffer.index(b"\x02")
                    if len(buffer) < stx_idx + 3:
                        break

                    # Read length bytes
                    len_high = buffer[stx_idx + 1]
                    len_low = buffer[stx_idx + 2]
                    payload_len = (len_high << 8) | len_low

                    frame_len = 1 + 2 + payload_len + 1  # STX + LEN + payload + LRC
                    if len(buffer) < stx_idx + frame_len:
                        break

                    frame = buffer[stx_idx : stx_idx + frame_len]
                    buffer = buffer[stx_idx + frame_len :]

                    self._command_log.append(frame)
                    response = self._process_frame(frame)
                    if response:
                        writer.write(response)
                        await writer.drain()
        except asyncio.CancelledError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            logger.info("passti_sim_client_disconnected", addr=addr)

    def _process_frame(self, frame: bytes) -> bytes | None:
        """Process PASSTI frame and return response."""
        try:
            from protocols.passti.frame import parse_response
            parsed = parse_response(frame)
        except Exception as e:
            logger.warning("passti_sim_parse_error", error=str(e))
            return None

        # The frame parser treats it as a response, but we need the command from payload
        # For a command frame: STX LEN-H LEN-L EF 01 CMD DATA LRC
        # payload starts at index 3
        if len(frame) < 6:
            return None

        payload = frame[3:-1]  # Exclude STX, LEN, LRC
        if len(payload) < 3:
            return None

        cmd = payload[2]

        if cmd == 0x02:  # CheckBalance
            return self._build_check_balance_response()
        elif cmd == 0x03:  # Deduct
            return self._build_deduct_response()
        elif cmd == 0x04:  # CancelDeduct
            return self._build_cancel_response()
        elif cmd == 0x05:  # GetLastTransaction
            return self._build_deduct_response()
        elif cmd == 0x01 or cmd == 0x0C:  # INIT
            return self._build_init_response()
        else:
            return self._build_error_response(0x01, 0x10, 0x01)

    def _build_check_balance_response(self) -> bytes:
        """Build CheckBalance success response (V1.12 §III.B)."""
        body = (
            bytes([self._card_type])
            + bytes.fromhex(self._card_number)
            + (10000).to_bytes(4, "big")
        )
        return build_response(0x00, b"\x00\x00\x00", body)

    def _build_deduct_response(self) -> bytes:
        """Build Deduct response based on configured status (V1.12 §III.C)."""
        if self._next_status == "SUCCESS":
            body = (
                bytes([self._card_type])
                + bytes.fromhex(self._mid)
                + bytes.fromhex(self._tid)
                + bytes.fromhex("26042612000000")[:7]  # ddmmyyyyhhmmss BCD
                + bytes.fromhex(self._card_number)
                + (500).to_bytes(4, "big")
                + (8700).to_bytes(4, "big")
                + self._transaction_counter.to_bytes(4, "big")
            )
            self._transaction_counter += 1
            return build_response(0x00, b"\x00\x00\x00", body)
        elif self._next_status == "LOST_CONTACT":
            return self._build_error_response(0x01, 0x10, 0x05)
        elif self._next_status == "INSUFFICIENT_BALANCE":
            return self._build_error_response(0x01, 0x10, 0x04)
        elif self._next_status == "WRONG_CARD":
            return self._build_error_response(0x01, 0x10, 0x06)
        else:
            return self._build_error_response(0x01, 0x10, 0x01)

    def _build_cancel_response(self) -> bytes:
        """Build CancelDeduct success response."""
        return build_response(0x00, b"\x00\x00\x00")

    def _build_init_response(self) -> bytes:
        """Build INIT success response: status + MID(8) + TID(4)."""
        body = bytes.fromhex(self._mid) + bytes.fromhex(self._tid)
        return build_response(0x00, b"\x00\x00\x00", body)

    def _build_error_response(self, b1: int, b2: int, b3: int) -> bytes:
        """Build a status-error response frame (resp_code 0x00)."""
        return build_response(0x00, bytes([b1, b2, b3]))

    # Configuration
    def set_next_status(self, status: str) -> None:
        self._next_status = status

    def set_card_type(self, card_type: int) -> None:
        self._card_type = card_type

    def get_command_log(self) -> list[bytes]:
        return self._command_log.copy()

    def clear_command_log(self) -> None:
        self._command_log.clear()
