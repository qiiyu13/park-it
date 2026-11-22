"""Snapshot file serving + archive management routes."""

import pathlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin, require_operator
from api.app.models.gate import Gate
from api.app.models.parking_transaction import ParkingTransaction
from api.app.models.snapshot import Snapshot
from api.database import get_db
from shared.logging import get_logger

logger = get_logger("snapshot_routes")
router = APIRouter(prefix="/snapshots", tags=["Snapshots"])


@router.get("")
async def list_snapshots(
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    gate_id: int | None = None,
    snapshot_type: str | None = Query(None, pattern="^(entry|exit)$"),
    q: str | None = Query(None, description="plat / barcode"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> dict:
    """Paginated snapshot archive with transaction/gate context."""
    stmt = (
        select(Snapshot, ParkingTransaction, Gate)
        .outerjoin(
            ParkingTransaction,
            ParkingTransaction.id == Snapshot.parking_transaction_id,
        )
        .outerjoin(Gate, Gate.id == Snapshot.gate_id)
    )

    if date_from:
        try:
            start = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
            stmt = stmt.where(Snapshot.created_at >= start)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from tidak valid")
    if date_to:
        try:
            end = datetime.fromisoformat(date_to).replace(tzinfo=UTC) + timedelta(days=1)
            stmt = stmt.where(Snapshot.created_at < end)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to tidak valid")
    if gate_id is not None:
        stmt = stmt.where(Snapshot.gate_id == gate_id)
    if snapshot_type:
        stmt = stmt.where(Snapshot.snapshot_type == snapshot_type)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            (ParkingTransaction.plate_number.ilike(needle))
            | (ParkingTransaction.barcode.ilike(needle))
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        stmt.order_by(Snapshot.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()

    items = []
    for snap, tx, gate in rows:
        items.append(
            {
                "id": snap.id,
                "created_at": snap.created_at.isoformat() if snap.created_at else None,
                "gate_id": snap.gate_id,
                "gate_code": gate.code if gate else None,
                "gate_name": gate.name if gate else None,
                "gate_type": snap.gate_type,
                "snapshot_type": snap.snapshot_type,
                "filename": snap.filename,
                "file_size": snap.file_size,
                "camera_name": snap.camera_name,
                "transaction_id": snap.parking_transaction_id,
                "plate_number": tx.plate_number if tx else None,
                "barcode": tx.barcode if tx else None,
                "image_url": f"/api/snapshots/{snap.id}/image",
            }
        )

    size_expr = func.coalesce(func.sum(Snapshot.file_size), 0)
    total_size = (await db.execute(select(size_expr))).scalar_one()

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "stats": {"count": total, "total_size": int(total_size or 0)},
    }


@router.get("/{snapshot_id}/image")
async def get_snapshot_image(
    snapshot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> FileResponse:
    """Serve snapshot image file by Snapshot DB id."""
    snapshot = await db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    path = Path(snapshot.file_path)
    if not path.exists():
        logger.warning("snapshot_file_missing", snapshot_id=snapshot_id, path=str(path))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot file not found")

    return FileResponse(path, media_type="image/jpeg", filename=snapshot.filename)


@router.delete("/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> dict:
    """Delete one snapshot (file + row) and detach it from transactions."""
    snapshot = await db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    from workers.critical.snapshot_worker import SNAPSHOT_DIR

    try:
        path = pathlib.Path(snapshot.file_path).resolve()
        root = SNAPSHOT_DIR.resolve()
        if path.parent == root or root in path.parents:
            path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("snapshot_unlink_failed", snapshot_id=snapshot_id, error=str(e))

    await db.execute(
        update(ParkingTransaction)
        .where(ParkingTransaction.entry_snapshot_id == snapshot_id)
        .values(entry_snapshot_id=None)
    )
    await db.execute(
        update(ParkingTransaction)
        .where(ParkingTransaction.exit_snapshot_id == snapshot_id)
        .values(exit_snapshot_id=None)
    )
    await db.execute(delete(Snapshot).where(Snapshot.id == snapshot_id))
    await db.commit()
    logger.info("snapshot_deleted", snapshot_id=snapshot_id)
    return {"success": True}


@router.post("/purge")
async def purge_snapshots(
    current_user: dict = Depends(require_admin),
) -> dict:
    """Run the retention job immediately (same rules as the 03:30 cron)."""
    from workers.background.cleanup_worker import cleanup_old_snapshots

    result = await cleanup_old_snapshots(None)
    return result
