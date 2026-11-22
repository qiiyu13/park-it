"""HTTP client for booth_bridge to call API.

Handles gate config fetch + booth-authenticated payment endpoints.

Retry policy
------------
``GET`` is idempotent — retry on any transient connection/timeout error
(but not on HTTP 4xx/5xx, since the server responded deterministically).

``POST`` is *not* idempotent for payment endpoints (``/api/payments/rfid/booth``,
``/api/payments/emoney/booth-result``). A retry after the request may have
reached the server can double-process. We therefore retry only when the
request provably never left this host:

* ``ConnectionRefusedError`` — TCP RST on connect, no bytes sent.
* ``socket.gaierror`` — DNS failed, no socket created.

Timeouts, ``ConnectionResetError``, ``BrokenPipeError`` and HTTP errors are
*not* retried for POST: any of these can mean the server already processed
the request, and re-POSTing a deduction would be worse than reporting failure.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from shared.logging import get_logger

logger = get_logger("booth_api_client")

_MAX_ATTEMPTS = 3
_BACKOFF_S = 0.5

# POST: only retry when the request *cannot* have reached the server.
_POST_SAFE_RETRY = (ConnectionRefusedError, socket.gaierror)

# GET: idempotent — any transient socket error is fine to retry.
_GET_TRANSIENT = (OSError, TimeoutError)


def _is_retryable_post(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return False  # Server responded — do not retry.
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, _POST_SAFE_RETRY)
    return isinstance(exc, _POST_SAFE_RETRY)


def _is_retryable_get(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        # urllib wraps the underlying socket error in .reason; OSError covers
        # ConnectionRefused/Reset/gaierror, TimeoutError covers socket.timeout
        # (alias since Python 3.10).
        return isinstance(reason, _GET_TRANSIENT)
    return isinstance(exc, _GET_TRANSIENT)


class ApiClient:
    """Thin async HTTP client using urllib via threads (avoids extra deps)."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._post_sync, path, body)

    async def _get(self, path: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_sync, path)

    def _get_sync(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_exc: BaseException | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                req = urllib.request.Request(
                    url, headers={"X-API-Key": self.api_key}, method="GET"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                last_exc = e
                if attempt < _MAX_ATTEMPTS and _is_retryable_get(e):
                    logger.warning("api_get_retry", path=path, attempt=attempt, error=str(e))
                    time.sleep(_BACKOFF_S * attempt)
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    def _post_sync(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode()
        last_exc: BaseException | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Key": self.api_key,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                last_exc = e
                if attempt < _MAX_ATTEMPTS and _is_retryable_post(e):
                    logger.warning("api_post_retry", path=path, attempt=attempt, error=str(e))
                    time.sleep(_BACKOFF_S * attempt)
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    async def fetch_gate(self, gate_code: str) -> dict[str, Any] | None:
        try:
            return await self._get(f"/api/gates/by-code/{gate_code}")
        except Exception as e:
            logger.error("fetch_gate_failed", gate_code=gate_code, error=str(e))
            return None

    async def rfid_exit(self, gate_id: str, gate_out_id: int, card_number: str) -> dict[str, Any]:
        try:
            return await self._post(
                "/api/payments/rfid/booth",
                {"gate_id": gate_id, "gate_out_id": gate_out_id, "card_number": card_number},
            )
        except Exception as e:
            logger.error("rfid_exit_failed", card=card_number, error=str(e))
            return {"success": False, "message": str(e)}

    async def take_pending_open(self, booth_code: str) -> dict[str, Any] | None:
        """Poll + take an admin-queued open for any OUT gate of this booth."""
        try:
            return await self._post(
                "/api/pos/pending-open", {"booth_code": booth_code}
            )
        except Exception as e:
            logger.warning("pending_open_poll_failed", error=str(e))
            return {"command": None}

    async def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """POST /api/pos/heartbeat. Returns ``None`` on transport failure.

        Heartbeats are best-effort: the server treats absence as staleness,
        so we never raise from this method — a failed POST is recorded as a
        warning and the next tick will try again. The retry policy in
        ``_post_sync`` still applies (timeouts NOT retried, so we don't
        spam the server with duplicate writes when it's overloaded).
        """
        try:
            return await self._post("/api/pos/heartbeat", payload)
        except Exception as e:
            logger.warning("heartbeat_failed", error=str(e))
            return None
