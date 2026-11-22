"""Background cleanup worker jobs."""

import pathlib
from datetime import UTC, datetime, timedelta

from shared.logging import get_logger

logger = get_logger("cleanup_worker")

SNAPSHOT_RETENTION_MONTHS = 6
SESSION_RETENTION_DAYS = 90
PENDING_PAYMENT_TIMEOUT_MINUTES = 5


async def cleanup_old_sessions(ctx) -> dict:
    """Clean up old completed parking transactions.

    Deletes transactions older than SESSION_RETENTION_DAYS that are COMPLETED.
    ACTIVE transactions are never deleted. Child audit rows keep their history
    but are detached (FK columns set NULL) so the DELETE cannot fail on a
    foreign-key constraint.
    """
    from sqlalchemy import delete, select, update

    from api.app.models import (
        AbandonedVehicleLog,
        EmoneyTransaction,
        ManualOpenLog,
        OperatorAlert,
        ParkingTransaction,
        Snapshot,
    )
    from api.database import AsyncSessionLocal

    cutoff = datetime.now(UTC) - timedelta(days=SESSION_RETENTION_DAYS)
    logger.info("cleanup_sessions_start", cutoff=cutoff.isoformat())

    try:
        async with AsyncSessionLocal() as db:
            tx_ids = select(ParkingTransaction.id).where(
                ParkingTransaction.status == "COMPLETED",
                ParkingTransaction.exit_time < cutoff,
            )
            # Detach child rows (all columns are nullable) rather than cascade
            # delete — emoney records must survive for settlement/audit.
            for model, column in (
                (EmoneyTransaction, EmoneyTransaction.parking_transaction_id),
                (ManualOpenLog, ManualOpenLog.parking_transaction_id),
                (AbandonedVehicleLog, AbandonedVehicleLog.parking_transaction_id),
                (OperatorAlert, OperatorAlert.parking_transaction_id),
                (Snapshot, Snapshot.parking_transaction_id),
            ):
                await db.execute(
                    update(model)
                    .where(column.in_(tx_ids))
                    .values(**{column.key: None})
                )

            result = await db.execute(
                delete(ParkingTransaction).where(
                    ParkingTransaction.status == "COMPLETED",
                    ParkingTransaction.exit_time < cutoff,
                )
            )
            await db.commit()

            deleted_count = result.rowcount
            logger.info("cleanup_sessions_complete", deleted=deleted_count)
            return {"status": "success", "deleted": deleted_count}
    except Exception as e:
        logger.error("cleanup_sessions_error", error=str(e))
        return {"status": "error", "message": str(e)}


async def _snapshot_retention_months(*, db_factory=None) -> int:
    """Months of snapshots to keep (setting ``snapshot_keep_months``; 0 = forever)."""
    from sqlalchemy import select

    from api.app.models.setting import Setting

    factory = db_factory
    if factory is None:
        from api.database import AsyncSessionLocal

        factory = AsyncSessionLocal

    try:
        async with factory() as db:
            raw = (
                await db.execute(
                    select(Setting.value).where(Setting.key == "snapshot_keep_months")
                )
            ).scalar_one_or_none()
        if raw in (None, ""):
            return SNAPSHOT_RETENTION_MONTHS
        return max(0, int(str(raw).strip()))
    except (ValueError, TypeError):
        logger.warning("snapshot_retention_invalid_setting")
    except Exception as e:
        logger.warning("snapshot_retention_setting_read_failed", error=str(e))
    return SNAPSHOT_RETENTION_MONTHS


async def cleanup_old_snapshots(ctx) -> dict:
    """Apply snapshot retention (Hapus Otomatis).

    Every snapshot from the last ``months`` months is kept; anything older is
    deleted (files + rows, transaction pointers nulled). A month is 30 days.
    Files without a DB row (crashed jobs) are swept by mtime too.
    """
    from sqlalchemy import delete, select, update

    from api.app.models import ParkingTransaction, Snapshot
    from api.database import AsyncSessionLocal
    from workers.critical.snapshot_worker import SNAPSHOT_DIR

    months = await _snapshot_retention_months(db_factory=AsyncSessionLocal)
    if months == 0:
        logger.info("cleanup_snapshots_disabled")
        return {"status": "skipped", "reason": "retention is 0 (keep forever)"}

    cutoff = datetime.now(UTC) - timedelta(days=30 * months)
    logger.info("cleanup_snapshots_start", cutoff=cutoff.isoformat(), months=months)

    deleted_files = 0
    deleted_rows = 0
    try:
        snapshot_root = SNAPSHOT_DIR.resolve()

        # Orphan files (no row, e.g. crashed job) are swept by mtime.
        for filepath in SNAPSHOT_DIR.glob("*.jpg"):
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=UTC)
            if mtime < cutoff:
                filepath.unlink(missing_ok=True)
                deleted_files += 1

        async with AsyncSessionLocal() as db:
            doomed = (
                await db.execute(select(Snapshot).where(Snapshot.created_at < cutoff))
            ).scalars().all()
            ids = [r.id for r in doomed]

            for row in doomed:
                path = pathlib.Path(row.file_path)
                try:
                    resolved = path.resolve()
                    # Only unlink inside the managed snapshot dir.
                    if snapshot_root in resolved.parents or resolved.parent == snapshot_root:
                        resolved.unlink(missing_ok=True)
                        deleted_files += 1
                except OSError as e:
                    logger.warning("snapshot_file_unlink_failed", path=row.file_path, error=str(e))

            if ids:
                await db.execute(
                    update(ParkingTransaction)
                    .where(ParkingTransaction.entry_snapshot_id.in_(ids))
                    .values(entry_snapshot_id=None)
                )
                await db.execute(
                    update(ParkingTransaction)
                    .where(ParkingTransaction.exit_snapshot_id.in_(ids))
                    .values(exit_snapshot_id=None)
                )
                result = await db.execute(delete(Snapshot).where(Snapshot.id.in_(ids)))
                deleted_rows = result.rowcount
            await db.commit()
    except Exception as e:
        logger.error("cleanup_snapshots_error", error=str(e))
        return {"status": "error", "message": str(e)}

    logger.info(
        "cleanup_snapshots_complete", deleted_files=deleted_files, deleted_rows=deleted_rows
    )
    return {"status": "success", "deleted_files": deleted_files, "deleted_rows": deleted_rows}


async def timeout_pending_payments(ctx) -> dict:
    """Reset PENDING e-money transactions that have been stuck too long.

    If the PASSTI reader never responds, transactions stay in PENDING forever.
    This job resets them so the operator can retry with a different payment method.
    """
    from sqlalchemy import select

    from api.app.models import ParkingTransaction
    from api.database import AsyncSessionLocal

    cutoff = datetime.now(UTC) - timedelta(minutes=PENDING_PAYMENT_TIMEOUT_MINUTES)
    logger.info("timeout_pending_start", cutoff=cutoff.isoformat())

    try:
        async with AsyncSessionLocal() as db:
            # Find stuck PENDING transactions
            result = await db.execute(
                select(ParkingTransaction).where(
                    ParkingTransaction.status == "ACTIVE",
                    ParkingTransaction.payment_method == "PENDING",
                    ParkingTransaction.updated_at < cutoff,
                )
            )
            stuck_txs = result.scalars().all()

            reset_count = 0
            for tx in stuck_txs:
                tx.payment_method = None
                tx.fee = None
                reset_count += 1
                logger.warning(
                    "pending_payment_timeout",
                    transaction_id=tx.id,
                    updated_at=tx.updated_at.isoformat() if tx.updated_at else None,
                )

            if reset_count > 0:
                await db.commit()

            logger.info("timeout_pending_complete", reset_count=reset_count)
            return {"status": "success", "reset_count": reset_count}
    except Exception as e:
        logger.error("timeout_pending_error", error=str(e))
        return {"status": "error", "message": str(e)}
