"""Telegram alert dispatch with per-alert deduplication.

Alerts are enqueued as ARQ jobs (the send itself lives in
notification_worker). A Redis SET NX guard with a TTL keeps a persistent
condition (gate down for hours) from flooding the chat: the first
notification goes out, repeats are suppressed until the TTL expires.

Everything is best-effort: alerting must never break the caller it is
protecting. Unconfigured bot/chat → logged once at debug level per call
site's own discretion (no raise).
"""

from __future__ import annotations

from shared.logging import get_logger

logger = get_logger("alerting")

# Default suppression window per alert key: one message per condition per hour.
ALERT_DEDUP_TTL_S = 3600


async def enqueue_alert(ctx, key: str, message: str, *, dedup_ttl_s: int = ALERT_DEDUP_TTL_S) -> bool:
    """Queue a Telegram alert unless an identical one was sent within the TTL.

    Args:
        ctx: ARQ context (uses ctx["redis"] for dedup and enqueue).
        key: Stable condition identifier, e.g. "gate_down:GIN01".
        message: HTML-formatted alert body.
        dedup_ttl_s: Suppression window for this key.

    Returns:
        True if an alert was enqueued (or already being sent), False if
        skipped (dedup hit or infrastructure unavailable).
    """
    from shared.config import get_settings

    settings = get_settings()
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        logger.debug("alert_skipped_not_configured", key=key)
        return False

    redis = ctx.get("redis")
    if redis is None:
        logger.warning("alert_skipped_no_redis", key=key)
        return False

    try:
        first = await redis.set(
            f"alert:dedup:{key}",
            "1",
            ex=dedup_ttl_s,
            nx=True,
        )
        if not first:
            return False  # duplicate within suppression window
        await redis.enqueue_job(
            "send_telegram_alert",
            settings.telegram_chat_id,
            message,
            _queue_name="arq:queue:background",
        )
        logger.info("alert_enqueued", key=key)
        return True
    except Exception as e:
        # Never let alerting failures propagate into the guarded path.
        logger.error("alert_enqueue_failed", key=key, error=str(e))
        return False
