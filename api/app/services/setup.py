"""Setup wizard service — token redemption, session lifecycle, state I/O."""

from __future__ import annotations

import asyncio
import hmac
import secrets
import shlex
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

# Installer-generated setup tokens auto-expire after this many seconds — even
# if never redeemed. Protects against tokens leaked into shell history that
# the operator forgot about.
SETUP_TOKEN_MAX_AGE_SECONDS = 24 * 60 * 60

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.setting import Setting
from api.app.models.setup_session import SetupSession
from api.app.models.user import User
from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("setup_service")

SETUP_TOPOLOGY = Literal["combo", "server_only", "booth_only", "unknown"]


def _read_disk_token(path: Path, label: str) -> str | None:
    """Read a token file written by the installer.

    Returns None if absent, unreadable, empty, or older than
    SETUP_TOKEN_MAX_AGE_SECONDS. Stale tokens are unlinked as a side effect
    so they don't accumulate.
    """
    if not path.exists():
        return None
    try:
        stat = path.stat()
    except OSError as exc:
        logger.warning(f"{label}_stat_failed", error=str(exc))
        return None

    age = time.time() - stat.st_mtime
    if age > SETUP_TOKEN_MAX_AGE_SECONDS:
        logger.warning(f"{label}_expired", age_seconds=int(age))
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning(f"{label}_unreadable", error=str(exc))
        return None
    return token or None


def read_setup_token() -> str | None:
    """Read installer-generated setup token from disk."""
    return _read_disk_token(Path(get_settings().setup_token_path), "setup_token")


def read_enroll_token() -> str | None:
    """Read installer-generated booth enrollment token from disk.

    Reusable: a single token enrolls every booth brought online during the
    install window. Not deleted on redeem.
    """
    return _read_disk_token(Path(get_settings().enroll_token_path), "enroll_token")


def delete_setup_token() -> None:
    """Delete the on-disk token after successful redeem."""
    path = Path(get_settings().setup_token_path)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("setup_token_unlink_failed", error=str(exc))


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def setup_complete(db: AsyncSession) -> bool:
    """Return True if setup_complete setting is true."""
    result = await db.execute(select(Setting).where(Setting.key == "setup_complete"))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    return (row.value or "").lower() == "true"


async def mark_setup_complete(db: AsyncSession, *, complete: bool = True) -> None:
    """Flip setup_complete flag (insert row if absent)."""
    result = await db.execute(select(Setting).where(Setting.key == "setup_complete"))
    row = result.scalar_one_or_none()
    if row is None:
        row = Setting(
            key="setup_complete",
            value="true" if complete else "false",
            value_type="bool",
            label="Setup wizard complete",
            description="Set true after wizard finalize.",
            group="system",
            is_system=True,
        )
        db.add(row)
    else:
        row.value = "true" if complete else "false"
    await db.commit()


async def has_any_admin(db: AsyncSession) -> bool:
    result = await db.execute(
        select(func.count()).select_from(User).where(User.role == "admin")
    )
    return (result.scalar() or 0) > 0


async def create_session(db: AsyncSession) -> SetupSession:
    """Create a fresh wizard session row with random token."""
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    session = SetupSession(
        session_token=token,
        current_step="welcome",
        data={},
        expires_at=datetime.now(UTC)
        + timedelta(seconds=settings.setup_session_ttl_seconds),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session_by_token(db: AsyncSession, token: str) -> SetupSession | None:
    result = await db.execute(
        select(SetupSession).where(SetupSession.session_token == token)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    if session.expires_at < datetime.now(UTC):
        await db.delete(session)
        await db.commit()
        return None
    return session


async def save_session_step(
    db: AsyncSession,
    session: SetupSession,
    *,
    step: str,
    data: dict[str, Any],
) -> SetupSession:
    """Merge step data into the session's JSONB blob."""
    merged = dict(session.data or {})
    merged[step] = data
    session.current_step = step
    session.data = merged
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session: SetupSession) -> None:
    await db.delete(session)
    await db.commit()


async def detect_topology() -> SETUP_TOPOLOGY:
    """Best-effort topology detection from systemd + udev symlinks."""

    async def unit_active(name: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="ignore").strip() == "active"

    has_server = await unit_active("parking-api")
    has_bridge = await unit_active("booth-bridge")
    has_local_serial = any(Path("/dev").glob("parking-*"))

    if has_server and has_bridge and has_local_serial:
        return "combo"
    if has_server and not has_local_serial:
        return "server_only"
    if not has_server and has_bridge:
        return "booth_only"
    return "unknown"


async def run_script_json(script: str, *args: str, timeout: float = 30.0) -> tuple[bool, str, str]:
    """Run a script (optionally via sudo) and return (ok, stdout, stderr)."""
    cmd = [script, *args]
    logger.info("setup_script_invoke", cmd=" ".join(shlex.quote(c) for c in cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return False, "", f"script timed out after {timeout:.0f}s"
    return (
        proc.returncode == 0,
        stdout.decode("utf-8", errors="ignore"),
        stderr.decode("utf-8", errors="ignore"),
    )
