"""Compass gate controller protocol.

Implements the TCP-based protocol used by Compass gate controllers.
Commands are wrapped with \xa6 prefix and \xa9 suffix.
"""

import asyncio
import select
import socket
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import serial


def build_command(cmd: bytes) -> bytes:
    """Wrap raw command in Compass frame.

    Args:
        cmd: Raw command bytes

    Returns:
        Framed command: \xa6 <cmd> \xa9
    """
    return bytes([0xA6]) + cmd + bytes([0xA9])


def cmd_trig1() -> bytes:
    """Pulse relay 1 for 1s — SINGLE relay mode open."""
    return build_command(b"TRIG1")


def cmd_trig2() -> bytes:
    """Pulse relay 2 for 1s."""
    return build_command(b"TRIG2")


def cmd_open1() -> bytes:
    """Open gate with interlocking: relay2 off, relay3 off, relay1 on 1s — DUAL/TRIPLE."""
    return build_command(b"OPEN1")


def cmd_close1() -> bytes:
    """Close gate with interlocking: relay1 off, relay3 off, relay2 on 1s — DUAL/TRIPLE."""
    return build_command(b"CLOSE1")


def cmd_stop1() -> bytes:
    """Brake gate motor: relay1 off, relay2 off, relay3 on 1s — TRIPLE only."""
    return build_command(b"STOP1")


def cmd_stat() -> bytes:
    """Request controller status."""
    return build_command(b"STAT")


def cmd_mt(track: str) -> bytes:
    """Play MP3 track on controller.

    Args:
        track: Track number string (e.g. '00007')
    """
    return build_command(f"MT{track}".encode())


def cmd_ds(line1: str, line2: str = "") -> bytes:
    """Show two-line text on controller LED display.

    Args:
        line1: First line text
        line2: Second line text
    """
    text = line1.encode() + b"|" + line2.encode()
    return build_command(b"DSD913003" + text)


def cmd_dsu() -> bytes:
    """Reset controller LED display."""
    return build_command(b"DSU")


def cmd_rss(
    interval_100ms: int = 2,
    *,
    in1_on: bool = True,
    in1_off: bool = True,
    in2_on: bool = True,
    in2_off: bool = False,
    in3_on: bool = True,
    in3_off: bool = True,
    in4_on: bool = True,
    in4_off: bool = False,
    play_end: bool = False,
    no_track: bool = False,
    wiegand: bool = True,
) -> bytes:
    """Configure RSS push mode — controller auto-pushes input events.

    Args:
        interval_100ms: Resend interval in units of 100ms (1–99). Default 2 = 200ms.
        in1_on/off ... wiegand: Enable push for each event type.
    """
    flags = "".join([
        "1" if in1_on else "0",
        "1" if in1_off else "0",
        "1" if in2_on else "0",
        "1" if in2_off else "0",
        "1" if in3_on else "0",
        "1" if in3_off else "0",
        "1" if in4_on else "0",
        "1" if in4_off else "0",
        "1" if play_end else "0",
        "1" if no_track else "0",
        "1" if wiegand else "0",
    ])
    return build_command(f"RSS{interval_100ms:02d}{flags}".encode())


def cmd_ack(signal: str) -> bytes:
    """Build RSS acknowledgement command. E.g. cmd_ack('IN2ON') → IN2ONOK."""
    return build_command(f"{signal}OK".encode())


def cmd_pr3(data: bytes) -> bytes:
    """Send data to serial port 1 at 9600 baud (standard printer baud rate)."""
    return build_command(b"PR3" + data)


def cmd_qr5(frame: bytes) -> bytes:
    """Send data to Serial2 (PASSTI reader passthrough).

    Args:
        frame: PASSTI command frame
    """
    return build_command(b"QR5" + frame)


class CompassTransport:
    """TCP transport for Compass gate controller."""

    SEND_TIMEOUT_S = 3.0
    last_error: str | None = None  # why the link was last torn down (for logs)

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None

    def connect(self, timeout: float = 5.0) -> None:
        """Establish TCP connection to controller with keepalive."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        self._sock.connect((self.host, self.port))
        self._enable_keepalive(self._sock)
        # Fixed write budget. recv_async waits with select() instead of
        # settimeout(), so a 0.5s read poll no longer shrinks the send timeout —
        # that turned one slow ACK into a teardown and a multi-hour lockout.
        self._sock.settimeout(self.SEND_TIMEOUT_S)

    @staticmethod
    def _enable_keepalive(sock: socket.socket) -> None:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for opt, val in (
            (getattr(socket, "TCP_KEEPIDLE", None), 10),
            (getattr(socket, "TCP_KEEPINTVL", None), 5),
            (getattr(socket, "TCP_KEEPCNT", None), 3),
        ):
            if opt is not None:
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, opt, val)
                except OSError:
                    pass

    def close(self) -> None:
        """Close TCP connection gracefully (FIN; queued bytes still flushed)."""
        if self._sock:
            self._sock.close()
            self._sock = None

    def abort(self) -> None:
        """Close with RST (SO_LINGER 0) for long-lived daemon links.

        PCLess/Compass controllers accept a single TCP client. A graceful FIN on
        a stalled link can leave the controller holding the old session, so it
        answers ping but refuses every new connect (ECONNREFUSED) for hours.
        RST makes it drop the session at once. Not for send-then-close callers:
        RST discards unsent bytes (e.g. a ticket still in the send buffer).
        """
        if self._sock:
            try:
                self._sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
            except OSError:
                pass
            self.close()

    def send(self, command: bytes) -> None:
        """Send command to controller (blocks up to SEND_TIMEOUT_S)."""
        if self._sock is None:
            raise RuntimeError("Not connected")
        self._sock.sendall(command)

    def send_recv(self, command: bytes, timeout: float = 1.0) -> bytes:
        """Send command and read response."""
        if self._sock is None:
            raise RuntimeError("Not connected")
        self._sock.settimeout(timeout)
        self._sock.sendall(command)
        try:
            return self._sock.recv(1024)
        except TimeoutError:
            return b""

    async def recv_async(self, timeout: float = 0.5) -> bytes:
        """Async recv via executor — doesn't block event loop.

        Used by RSS listener to receive pushed events without STAT polling.
        Reads are lock-free (TCP full-duplex); only writes need the caller's lock.

        Returns ``b""`` on read timeout (still connected, no data). On EOF (peer
        performed an orderly shutdown — recv returns 0 bytes) or a socket error
        the connection is torn down so ``is_connected()`` reports False. Without
        this the caller cannot distinguish "idle" from "dead" and would busy-spin
        on a half-open socket forever instead of reconnecting.
        """
        sock = self._sock
        if sock is None:
            return b""
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, self._recv_ready, sock, timeout)
        except (OSError, ValueError) as e:
            self.last_error = str(e)
            self.abort()
            return b""
        if data is None:
            return b""  # idle: no data within timeout
        if not data:
            # Orderly peer shutdown (FIN) — 0 bytes after select() said readable
            # means EOF. Tear down so the listener reconnects.
            self.last_error = "peer closed connection"
            self.abort()
        return data

    @staticmethod
    def _recv_ready(sock: socket.socket, timeout: float) -> bytes | None:
        """select() then recv — None on timeout. Leaves the socket timeout alone."""
        readable, _, _ = select.select([sock], [], [], timeout)
        return sock.recv(1024) if readable else None

    def is_connected(self) -> bool:
        """Check if socket is connected."""
        if self._sock is None:
            return False
        try:
            self._sock.getpeername()
            return True
        except Exception:
            return False


class SerialTransport:
    """RS232/USB serial transport for barrier gate controllers (e.g. Interface Barrier Gate v1.0).

    Mirrors CompassTransport interface so daemons can use either transport
    interchangeably. Same Compass framing protocol (\xa6...\xa9) over serial.
    PASSTI passthrough is NOT supported — serial controllers lack the QR5 tunnel.
    """

    def __init__(self, device: str, baudrate: int = 9600) -> None:
        self.device = device
        self.baudrate = baudrate
        self._ser: serial.Serial | None = None

    def connect(self, timeout: float = 5.0) -> None:
        import serial as _serial
        self._ser = _serial.Serial(
            port=self.device,
            baudrate=self.baudrate,
            bytesize=_serial.EIGHTBITS,
            parity=_serial.PARITY_NONE,
            stopbits=_serial.STOPBITS_ONE,
            timeout=timeout,
        )

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    abort = close  # ponytail: no session state on serial, same as close
    last_error: str | None = None

    def send(self, command: bytes) -> None:
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Not connected")
        self._ser.write(command)

    def send_recv(self, command: bytes, timeout: float = 1.0) -> bytes:
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("Not connected")
        self._ser.timeout = timeout
        self._ser.write(command)
        return self._ser.read(1024)

    async def recv_async(self, timeout: float = 0.5) -> bytes:
        if self._ser is None or not self._ser.is_open:
            return b""
        self._ser.timeout = timeout
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._ser.read, 1024)
        except Exception:
            # Device unplugged / port error — tear down so is_connected() flips
            # False and the listener reconnects instead of looping on a dead port.
            self.close()
            return b""

    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open
