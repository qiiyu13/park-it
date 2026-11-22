"""CompassTransport link handling against a local TCP peer (no controller)."""

import socket
import struct

from protocols.compass.protocol import CompassTransport


def _listener() -> socket.socket:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    return srv


async def test_idle_recv_keeps_link_and_send_budget():
    srv = _listener()
    t = CompassTransport(*srv.getsockname())
    t.connect(timeout=1.0)
    peer, _ = srv.accept()
    sock = t._sock
    assert sock is not None

    # Idle poll: no data, link stays up, send timeout not shrunk to the poll.
    assert await t.recv_async(timeout=0.05) == b""
    assert t.is_connected()
    assert sock.gettimeout() == CompassTransport.SEND_TIMEOUT_S

    peer.sendall(b"\xa6IN1ON\xa9")
    assert await t.recv_async(timeout=1.0) == b"\xa6IN1ON\xa9"

    # Peer FIN -> torn down with a reason, so the daemon reconnects and logs why.
    peer.close()
    assert await t.recv_async(timeout=1.0) == b""
    assert not t.is_connected()
    assert t.last_error == "peer closed connection"
    srv.close()


def test_abort_sends_rst_not_fin():
    srv = _listener()
    t = CompassTransport(*srv.getsockname())
    t.connect(timeout=1.0)
    peer, _ = srv.accept()
    sock = t._sock
    assert sock is not None
    linger = sock.getsockopt(socket.SOL_SOCKET, socket.SO_LINGER, 8)
    assert struct.unpack("ii", linger) == (0, 0)  # default: graceful close

    t.abort()
    assert t._sock is None
    # RST: the peer's read fails with ECONNRESET instead of a clean EOF.
    try:
        data = peer.recv(16)
    except ConnectionResetError:
        data = None
    assert data is None, f"expected RST, got clean read {data!r}"
    peer.close()
    srv.close()
