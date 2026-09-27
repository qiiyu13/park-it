"""ARQ worker settings."""

from zoneinfo import ZoneInfo

from arq import cron, func
from arq.connections import RedisSettings

from shared.config import get_settings

settings = get_settings()

# Cron schedules evaluate in this timezone. Without it they use the host TZ —
# a UTC container would fire the "02:00 Jakarta" settlement at 09:00 WIB,
# after the bank's morning cutoff.
JAKARTA_TZ = ZoneInfo(settings.app_timezone)


# Redis connection settings for ARQ
arq_redis_settings = RedisSettings(
    host=settings.redis_host,
    port=settings.redis_port,
    database=settings.redis_db,
    password=settings.redis_password or None,
)


class CriticalWorkerSettings:
    """Critical worker: handles print jobs (time-sensitive, blocks gate UX)."""

    redis_settings = arq_redis_settings
    queue_name = "arq:queue:critical"

    functions = [
        func("workers.critical.print_worker.print_ticket", name="print_ticket"),
        func("workers.critical.print_worker.print_receipt", name="print_receipt"),
        func("workers.critical.snapshot_worker.take_snapshot", name="take_snapshot"),
    ]

    max_tries = 3
    job_timeout = 30
    max_jobs = 10  # headroom for concurrent RTSP snapshots

    # 60s health-key refresh (TTL 61s) — see BackgroundWorkerSettings.
    health_check_interval = 60

    handle_signals = True


class BackgroundWorkerSettings:
    """Background worker: handles settlement, cleanup, notifications."""

    redis_settings = arq_redis_settings
    queue_name = "arq:queue:background"

    functions = [
        func("workers.background.settlement_worker.generate_settlement_file", name="generate_settlement_file"),
        func("workers.background.settlement_uploader.upload_settlement_job", name="upload_settlement_job"),
        func("workers.background.settlement_uploader.poll_settlement_responses", name="poll_settlement_responses"),
        func("workers.background.settlement_uploader.retry_stalled_settlements", name="retry_stalled_settlements"),
        func("workers.background.cleanup_worker.cleanup_old_sessions", name="cleanup_old_sessions"),
        func("workers.background.cleanup_worker.cleanup_old_snapshots", name="cleanup_old_snapshots"),
        func("workers.background.cleanup_worker.timeout_pending_payments", name="timeout_pending_payments"),
        func("workers.background.notification_worker.send_telegram_alert", name="send_telegram_alert"),
        func("workers.background.heartbeat_watcher.check_gate_heartbeats", name="check_gate_heartbeats"),
    ]

    # Cron schedules evaluate in this timezone (not the host's).
    timezone = JAKARTA_TZ

    # Refresh the ARQ health key every 60s (TTL 61s) so parking-doctor and
    # monitoring detect a dead worker within a minute — the ARQ default of
    # 1h would stay green for an hour after the worker wedged.
    health_check_interval = 60

    # Cron jobs
    cron_jobs = [
        # Daily settlement at 2 AM operational time (Asia/Jakarta).
        cron(
            "workers.background.settlement_worker.generate_settlement_file",
            name="generate_settlement_file",
            hour=2,
            minute=0,
        ),
        # Poll bank for .OK/.NOK every 15 minutes — fast enough for prompt
        # reconciliation, sparse enough to not hammer the bank's SFTP.
        cron(
            "workers.background.settlement_uploader.poll_settlement_responses",
            name="poll_settlement_responses",
            minute={0, 15, 30, 45},
        ),
        # Re-enqueue uploads stuck in GENERATED/FAILED (crash before enqueue,
        # SFTP outage outlasting in-job retries). Idempotent: the upload job
        # re-checks state before sending.
        cron(
            "workers.background.settlement_uploader.retry_stalled_settlements",
            name="retry_stalled_settlements",
            minute={7, 37},
        ),
        # Cleanup old data daily at 3 AM
        cron(
            "workers.background.cleanup_worker.cleanup_old_sessions",
            name="cleanup_old_sessions",
            hour=3,
            minute=0,
        ),
        # Timeout stuck PENDING e-money payments every 5 minutes
        cron(
            "workers.background.cleanup_worker.timeout_pending_payments",
            name="timeout_pending_payments",
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        # Page when a gate daemon stops heart-beating (independent of
        # Prometheus — works on any site with just a Telegram bot token).
        cron(
            "workers.background.heartbeat_watcher.check_gate_heartbeats",
            name="check_gate_heartbeats",
            minute={2, 12, 22, 32, 42, 52},
        ),
    ]

    # Retry settings
    max_tries = 3
    job_timeout = 300  # seconds (5 minutes for settlement)

    # Worker settings
    handle_signals = True
