"""Heartbeat watcher — alert when a gate daemon stops beating.

Runs on a cron in the background worker. Reads the active gates from the
DB and checks each daemon's `gate:heartbeat:{code}` key (60s TTL, written
every 30s). Missing key = daemon dead or wedged.

This is deliberately independent of Prometheus/Alertmanager: those require
infra on every site and were configured with an empty alertmanager target
(= rules evaluated into nothing). Telegram fires with just a bot token in
.env. Prometheus remains the richer path for whoever wires it up.
"""

from __future__ import annotations

from datetime import UTC, datetime

from shared.logging import get_logger

logger = get_logger("heartbeat_watcher")

# Consecutive misses before alerting — one missed beat (30s cadence, 60s TTL)
# is a blip; two means the daemon is really gone.
MIN_MISSES = 2


async def check_gate_heartbeats(ctx) -> dict:
    """Cron job: enqueue a Telegram alert for each gate whose heartbeat is stale."""
    from sqlalchemy import select

    from api.app.models import Gate
    from api.database import AsyncSessionLocal
    from shared.redis import redis_client
    from workers.background.alerting import enqueue_alert

    try:
        await redis_client.connect()
        redis = redis_client.client

        async with AsyncSessionLocal() as db:
            gates = (
                await db.execute(
                    select(Gate.code, Gate.name, Gate.direction).where(
                        Gate.is_active == True  # noqa: E712
                    )
                )
            ).all()

        offline = []
        for code, name, direction in gates:
            last = await redis.get(f"gate:heartbeat:{code}")
            if last is None:
                misses = await redis.incr(f"alert:hb_miss:{code}")
                await redis.expire(f"alert:hb_miss:{code}", 3600)
                if misses >= MIN_MISSES:
                    offline.append((code, name, direction))
            else:
                # Beat is fresh — reset the miss counter.
                await redis.delete(f"alert:hb_miss:{code}")

        # A gate that just came up for the first time also has no key; the
        # consecutive-miss counter means it must be absent for MIN_MISSES
        # runs before we page anyone. Dedup caps repeats to once per hour.
        for code, name, direction in offline:
            await enqueue_alert(
                ctx,
                key=f"gate_down:{code}",
                message=(
                    f"<b>Gate daemon offline</b>\n\n"
                    f"Gate: <code>{code}</code> ({name})\n"
                    f"Direction: {direction}\n"
                    f"Detected: {datetime.now(UTC).isoformat(timespec='seconds')}\n\n"
                    f"No heartbeat for {MIN_MISSES} consecutive checks. The lane is "
                    f"down — check <code>parking-daemon-gate-*@{code}</code>."
                ),
            )

        if offline:
            logger.warning("gate_heartbeats_offline", gates=[c for c, _, _ in offline])
        return {"status": "success", "offline": len(offline), "total": len(gates)}
    except Exception as e:
        logger.error("gate_heartbeat_check_failed", error=str(e))
        return {"status": "error", "message": str(e)}
