"""Background settlement worker job."""

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from shared.logging import get_logger
from workers.background.settlement_file import build_settlement_content, generate_filename

logger = get_logger("settlement_worker")

# Settlement files storage path
SETTLEMENT_DIR = os.environ.get("SETTLEMENT_DIR", "/var/lib/parking/settlements")

# Multibank v1.3 §I header has TrxCount(3 digits) → max 999 trx per file.
MAX_TRX_PER_FILE = 999

# All settlement timestamps and batch counters are in Asia/Jakarta. The bank
# expects local-time filenames, and the daily batch counter must reset on the
# operational day boundary (not UTC midnight).
JAKARTA_TZ = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Jakarta"))

# PASSTI card type code for QR Payment. Multibank v1.3 §I states cardtype 09
# does NOT need to be settled with the bank.
QR_CARD_TYPE_CODE = 0x09


async def generate_settlement_file(ctx, db=None) -> dict:
    """Generate daily settlement files from successful e-money transactions.

    Groups unsettled transactions by emoney_reader_id, generates one file
    per reader (MID/TID), stores file locally, creates EmoneySettlement record.

    Args:
        ctx: ARQ context dict (may contain redis client)
        db: Optional async DB session for testing. If None, creates a new session.
    """
    logger.info("generate_settlement_job_start")

    # Lease lock: prevent duplicate settlement runs (e.g. two workers, manual + cron).
    # Lock keyed by operational day in Jakarta TZ. 1h TTL safely outlives the job.
    # A Redis ERROR must not skip settlement (a blip at 02:00 meant no files at
    # all) — we proceed lockless and rely on SELECT FOR UPDATE SKIP LOCKED
    # below to serialise the actual row claiming.
    redis_client = ctx.get("redis") if ctx else None
    lock_acquired = False
    lock_key = None
    if redis_client is not None:
        day_key = datetime.now(JAKARTA_TZ).strftime("%Y%m%d")
        lock_key = f"lock:settlement:{day_key}"
        try:
            lock_acquired = await redis_client.set(lock_key, "1", nx=True, ex=3600)
        except Exception as e:
            logger.warning("settlement_lock_error_proceeding_unlocked", error=str(e))
            lock_key = None  # nothing to release
        else:
            if not lock_acquired:
                logger.warning("settlement_lock_held", lock_key=lock_key)
                return {
                    "status": "success",
                    "files_generated": 0,
                    "total_transactions": 0,
                    "skipped_locked": True,
                }

    try:
        return await _generate_locked(ctx, db)
    finally:
        # Release on completion so a legitimate same-day re-run (manual
        # trigger after the cron) can pick up newly arrived transactions.
        if lock_acquired and lock_key is not None:
            try:
                await redis_client.delete(lock_key)
            except Exception as e:
                logger.warning("settlement_lock_release_failed", error=str(e))


async def _generate_locked(ctx, db=None) -> dict:
    from api.app.models.emoney_reader import EmoneyReader
    from api.app.models.emoney_settlement import EmoneySettlement
    from api.app.models.emoney_transaction import EmoneyTransaction
    from api.database import AsyncSessionLocal

    os.makedirs(SETTLEMENT_DIR, exist_ok=True)

    files_generated = 0
    total_transactions = 0

    @asynccontextmanager
    async def _session():
        if db is not None:
            yield db
        else:
            async with AsyncSessionLocal() as session:
                yield session

    async with _session() as db:
        # Find all readers with unsettled SUCCESS transactions, excluding QR.
        # Multibank v1.3 §I: cardtype 09 (QR Payment) doesn't need to settle
        # with the bank (settled by the QR provider separately).
        reader_ids_result = await db.execute(
            select(EmoneyTransaction.emoney_reader_id)
            .where(
                EmoneyTransaction.settlement_batch_id.is_(None),
                EmoneyTransaction.status == "SUCCESS",
                EmoneyTransaction.emoney_reader_id.isnot(None),
                or_(
                    EmoneyTransaction.card_type_code != QR_CARD_TYPE_CODE,
                    EmoneyTransaction.card_type_code.is_(None),
                ),
            )
            .distinct()
        )
        reader_ids = [r[0] for r in reader_ids_result.all()]

        if not reader_ids:
            logger.info("generate_settlement_no_transactions")
            return {"status": "success", "files_generated": 0, "total_transactions": 0}

        now_jkt = datetime.now(JAKARTA_TZ)
        date_jkt_iso = now_jkt.date().isoformat()
        # Last batch number handed out per reader this run — used when Redis
        # INCR is unavailable so two chunks never share a filename (identical
        # names would silently overwrite the first file on disk).
        fallback_batch: dict[int, int] = {}

        for reader_id in reader_ids:
            # Get reader details
            reader = await db.get(EmoneyReader, reader_id)
            if not reader or not reader.mid or not reader.tid:
                logger.warning("generate_settlement_skip_no_mid_tid", reader_id=reader_id)
                continue

            # Fetch settle-eligible transactions for this reader (excluding QR).
            # SKIP LOCKED: a concurrent run (lockless after Redis error) claims
            # different rows instead of double-linking them into two files.
            tx_result = await db.execute(
                select(EmoneyTransaction)
                .where(
                    EmoneyTransaction.settlement_batch_id.is_(None),
                    EmoneyTransaction.status == "SUCCESS",
                    EmoneyTransaction.emoney_reader_id == reader_id,
                    or_(
                        EmoneyTransaction.card_type_code != QR_CARD_TYPE_CODE,
                        EmoneyTransaction.card_type_code.is_(None),
                    ),
                )
                .order_by(EmoneyTransaction.created_at)
                .with_for_update(skip_locked=True)
            )
            transactions = list(tx_result.scalars().all())

            # Rows without a settlement payload cannot be represented in the
            # file — an empty body line makes the bank reject the WHOLE file.
            # Leave them unsettled (retry after backfill) and complain loudly.
            unpayloaded = [t for t in transactions if not t.settlement_payload_hex]
            if unpayloaded:
                logger.error(
                    "generate_settlement_rows_missing_payload_skipped",
                    count=len(unpayloaded),
                    reader_id=reader_id,
                    tx_ids=[t.id for t in unpayloaded[:20]],
                )
                transactions = [t for t in transactions if t.settlement_payload_hex]

            if not transactions:
                continue

            redis = ctx.get("redis")

            # Multibank v1.3 §I: max 999 trx per file. Chunk and emit one file
            # per chunk with monotonically increasing batch_number (resets daily).
            for chunk_start in range(0, len(transactions), MAX_TRX_PER_FILE):
                chunk = transactions[chunk_start : chunk_start + MAX_TRX_PER_FILE]

                batch_number = await _next_batch_number(
                    redis, reader_id, date_jkt_iso, fallback_batch
                )

                chunk_total = sum(tx.amount_deducted for tx in chunk)

                filename = generate_filename(
                    settlement_datetime=now_jkt,
                    mid=reader.mid,
                    tid=reader.tid,
                    batch_number=batch_number,
                )

                tx_dicts = [
                    {"settlement_payload_hex": tx.settlement_payload_hex or ""}
                    for tx in chunk
                ]
                content = build_settlement_content(tx_dicts, chunk_total)

                # Write file
                file_path = os.path.join(SETTLEMENT_DIR, filename)
                with open(file_path, "w", encoding="ascii") as f:
                    f.write(content)

                # Compute hash
                file_hash = hashlib.sha256(content.encode("ascii")).hexdigest()

                # Create settlement record
                settlement = EmoneySettlement(
                    filename=filename,
                    file_path=file_path,
                    batch_date=now_jkt.date(),
                    batch_number=batch_number,
                    total_transactions=len(chunk),
                    total_amount=chunk_total,
                    status="GENERATED",
                    file_content_hash=file_hash,
                )
                db.add(settlement)
                await db.flush()  # Get settlement.id

                # Link transactions to settlement
                for tx in chunk:
                    tx.settlement_batch_id = settlement.id

                await db.commit()

                files_generated += 1
                total_transactions += len(chunk)

                logger.info(
                    "generate_settlement_file_created",
                    filename=filename,
                    reader_id=reader_id,
                    transactions=len(chunk),
                    amount=chunk_total,
                    batch_number=batch_number,
                )

                # Hand off to the upload job. The upload job raises arq.Retry
                # on transient failure; orphaned GENERATED/FAILED files (crash
                # before enqueue, exhausted retries) are swept by
                # retry_stalled_settlements cron.
                await _enqueue_upload(ctx, settlement.id)

    logger.info(
        "generate_settlement_job_complete",
        files_generated=files_generated,
        total_transactions=total_transactions,
    )

    return {
        "status": "success",
        "files_generated": files_generated,
        "total_transactions": total_transactions,
    }


async def _enqueue_upload(ctx: dict, settlement_id: int) -> None:
    """Enqueue the SFTP upload job for a freshly generated settlement.

    Best-effort: if the ARQ redis client isn't in ctx, log and skip — the
    settlement file is already on disk and the next cron tick will retry.
    """
    arq_redis = ctx.get("redis")
    if arq_redis is None:
        logger.warning("settlement_upload_no_arq_redis", settlement_id=settlement_id)
        return
    try:
        # ARQ context's `redis` is its own ArqRedis instance; it has enqueue_job.
        if hasattr(arq_redis, "enqueue_job"):
            await arq_redis.enqueue_job(
                "upload_settlement_job",
                settlement_id,
                _queue_name="arq:queue:background",
            )
        else:
            # In tests we may pass a plain mock — silently no-op.
            logger.debug("settlement_upload_skipped_no_arq", settlement_id=settlement_id)
    except Exception as e:
        logger.warning(
            "settlement_upload_enqueue_failed",
            settlement_id=settlement_id,
            error=str(e),
        )


async def _next_batch_number(
    redis, reader_id: int, date_iso: str, fallback_batch: dict[int, int] | None = None
) -> int:
    """Atomically allocate the next daily batch number for a reader.

    Multibank v1.3 §I: batch_no resets daily (in operational timezone). Uses
    Redis INCR for atomicity so concurrent settlement runs never collide.
    Falls back to a run-local counter when Redis is unavailable — returning
    a constant 1 would give two chunks the same timestamp+batch filename and
    the second file would overwrite the first on disk.
    """
    if fallback_batch is None:
        fallback_batch = {}
    if redis is None:
        fallback_batch[reader_id] = fallback_batch.get(reader_id, 0) + 1
        return fallback_batch[reader_id]
    try:
        batch_key = f"settlement:batch:{reader_id}:{date_iso}"
        n = await redis.incr(batch_key)
        # Set expiry only on the first INCR (n == 1) to avoid extending it.
        if n == 1:
            await redis.expire(batch_key, 172800)  # 48h: covers late-night settles
        return int(n)
    except Exception:
        logger.warning("settlement_batch_redis_unavailable", reader_id=reader_id)
        fallback_batch[reader_id] = fallback_batch.get(reader_id, 0) + 1
        return fallback_batch[reader_id]
