"""Background cleanup worker jobs."""

import pathlib
from datetime import UTC, datetime, timedelta

from shared.logging import get_logger

logger = get_logger("cleanup_worker")

SNAPSHOT_RETENTION_DAYS = 30
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


async def cleanup_old_snapshots(ctx) -> dict:
    """Delete expired snapshot files AND their database rows.

    Filesystem-only cleanup left `snapshots` rows pointing at deleted files,
    so /api/snapshots/{id}/image 404'd forever and the table grew without
    bound. Rows are deleted, and any transaction pointer to them is cleared.
    """
    from sqlalchemy import delete, select, update

    from api.app.models import ParkingTransaction, Snapshot
    from api.database import AsyncSessionLocal
    from workers.critical.snapshot_worker import SNAPSHOT_DIR

    cutoff = datetime.now(UTC) - timedelta(days=SNAPSHOT_RETENTION_DAYS)
    logger.info("cleanup_snapshots_start", cutoff=cutoff.isoformat())

    deleted_files = 0
    deleted_rows = 0
    try:
        snapshot_root = SNAPSHOT_DIR.resolve()

        # Orphan files (no row, e.g. crashed job) are still swept by mtime.
        for filepath in SNAPSHOT_DIR.glob("*.jpg"):
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=UTC)
            if mtime < cutoff:
                filepath.unlink(missing_ok=True)
                deleted_files += 1

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(select(Snapshot).where(Snapshot.created_at < cutoff))
            ).scalars().all()
            ids = [r.id for r in rows]

            for row in rows:
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
        "cleanup_snapshots_complete",
        deleted_files=deleted_files,
        deleted_rows=deleted_rows,
    )
    return {
        "status": "success",
        "deleted_files": deleted_files,
        "deleted_rows": deleted_rows,
    }


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
