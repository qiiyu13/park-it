"""Settlement upload and response processing for Multibank v1.3 §I + §II.

Two responsibilities live here:

1. **Upload** generated settlement files to the bank via SFTP. Atomic delivery
   pattern: write to ``<file>.partial`` then rename → bank polling never sees
   a half-written file.

2. **Poll** the bank's response files (``<basename>.OK`` / ``.NOK``) and
   reconcile per-transaction status onto the EmoneyTransaction rows.

Configuration is read from shared.config.Settings; see the
``settlement_sftp_*`` keys.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shared.logging import get_logger

logger = get_logger("settlement_uploader")

# How many times a bank-rejected transaction may be re-generated into a new
# settlement file before we stop and log loudly (a permanently invalid
# payload must not be resubmitted forever).
MAX_SETTLEMENT_RETRIES = 3

# Multibank v1.3 §II — Response Transaction Data, Status field
RESPONSE_STATUS_CODES: dict[str, str] = {
    "00": "Accepted",
    "01": "Invalid Format",
    "02": "Duplicate Data",
    "03": "Transaction count mismatch",
    "04": "Transaction amount mismatch",
    "05": "Invalid Merchant Terminal",
    "07": "Data Corrupt",
    "08": "Invalid Device SN",
    "09": "Invalid Bank Log",
    "10": "Invalid Filename Format",
    "11": "Invalid Header Format",
}


# ---------------------------------------------------------------------------
# Response file parsing (kept pure for unit tests)
# ---------------------------------------------------------------------------


def parse_ok_response(content: str) -> dict[str, Any]:
    """Parse a Multibank v1.3 §II response file body (.OK or .NOK).

    Format:
        Line 0: TrxType(2) + TrxCount(3) — header
        Line N: <settlement_payload_hex><status(2)>

    Returns a dict::

        {
            "trx_type": "01",
            "trx_count": 123,
            "results": [
                {
                    "settlement_payload_hex": "01...",
                    "status": "00",
                    "status_description": "Accepted",
                },
                ...
            ],
        }
    """
    lines = content.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
    if not lines or len(lines[0]) < 5:
        return {"trx_type": "", "trx_count": 0, "results": []}

    header = lines[0]
    trx_type = header[:2]
    try:
        trx_count = int(header[2:5])
    except ValueError:
        trx_count = 0

    results: list[dict[str, str]] = []
    for line in lines[1:]:
        if len(line) < 2:
            continue
        status = line[-2:]
        payload = line[:-2]
        results.append(
            {
                "settlement_payload_hex": payload.upper(),
                "status": status,
                "status_description": RESPONSE_STATUS_CODES.get(status, "Unknown"),
            }
        )

    return {"trx_type": trx_type, "trx_count": trx_count, "results": results}


def parse_nok_response(content: str) -> dict[str, Any]:
    """Parse a .NOK response file. Same format as .OK; semantically all
    transactions are rejected (header status applies file-wide)."""
    return parse_ok_response(content)


# ---------------------------------------------------------------------------
# SFTP transport
# ---------------------------------------------------------------------------


def _have_asyncssh() -> bool:
    try:
        import asyncssh  # noqa: F401

        return True
    except ImportError:
        return False


@asynccontextmanager
async def _sftp_session(
    host: str,
    port: int,
    username: str,
    key_path: str,
    known_hosts: str | None,
    connect_timeout: int = 30,
):
    """Yield an open SFTP client. Raises on auth/connect failure."""
    import asyncssh

    async with asyncssh.connect(
        host=host,
        port=port,
        username=username,
        client_keys=[key_path] if key_path else None,
        known_hosts=known_hosts if known_hosts else None,
        connect_timeout=connect_timeout,
    ) as conn, conn.start_sftp_client() as sftp:
        yield sftp


async def upload_settlement_file(
    file_path: str,
    *,
    host: str,
    port: int = 22,
    username: str,
    key_path: str,
    known_hosts: str | None = None,
    remote_dir: str = "/",
    connect_timeout: int = 30,
) -> bool:
    """Upload a settlement file via SFTP using atomic .partial→rename.

    Returns True on success. Raises asyncssh exceptions on connect/auth/IO
    failure so the caller (ARQ retry policy) can decide whether to retry.

    The bank polls the inbox for files matching the multibank filename pattern;
    writing to ``<name>.partial`` first and renaming on completion guarantees
    that polling never sees a half-written file.
    """
    if not Path(file_path).is_file():
        logger.error("settlement_upload_no_file", file_path=file_path)
        return False

    if not _have_asyncssh():
        logger.error("settlement_upload_asyncssh_missing")
        raise RuntimeError("asyncssh is required for SFTP upload")

    remote_name = os.path.basename(file_path)
    remote_dir = remote_dir.rstrip("/") or "/"
    tmp_remote = f"{remote_dir}/{remote_name}.partial"
    final_remote = f"{remote_dir}/{remote_name}"

    logger.info(
        "settlement_upload_start",
        file_path=file_path,
        host=host,
        remote=final_remote,
    )

    async with _sftp_session(
        host=host,
        port=port,
        username=username,
        key_path=key_path,
        known_hosts=known_hosts,
        connect_timeout=connect_timeout,
    ) as sftp:
        # Best-effort cleanup of any stale .partial from a previous run.
        try:
            await sftp.remove(tmp_remote)
        except Exception:
            pass
        await sftp.put(file_path, tmp_remote)
        await sftp.rename(tmp_remote, final_remote)

    logger.info("settlement_upload_complete", file_path=file_path, remote=final_remote)
    return True


async def fetch_response_file(
    settlement_filename: str,
    *,
    host: str,
    port: int = 22,
    username: str,
    key_path: str,
    known_hosts: str | None = None,
    remote_dir: str = "/",
    connect_timeout: int = 30,
) -> tuple[str | None, str | None]:
    """One-shot fetch attempt for the matching .OK/.NOK response file.

    Returns ``(extension, content)`` on hit (extension is "OK" or "NOK"),
    or ``(None, None)`` if neither file exists yet.

    The bank may write either file, so we try .OK first then .NOK.
    """
    import asyncssh

    base = settlement_filename
    if base.lower().endswith(".txt"):
        base = base[:-4]

    remote_dir = remote_dir.rstrip("/") or "/"

    async with _sftp_session(
        host=host,
        port=port,
        username=username,
        key_path=key_path,
        known_hosts=known_hosts,
        connect_timeout=connect_timeout,
    ) as sftp:
        for ext in ("OK", "NOK"):
            remote = f"{remote_dir}/{base}.{ext}"
            try:
                # asyncssh has no "read into memory" helper; use a temp file.
                local_tmp = f"/tmp/{base}.{ext}.fetched"
                await sftp.get(remote, local_tmp)
            except (FileNotFoundError, asyncssh.SFTPNoSuchFile):
                continue
            except OSError:
                # Some asyncssh versions raise plain OSError for "no such file".
                continue

            try:
                with open(local_tmp, encoding="ascii") as f:
                    content = f.read()
            finally:
                try:
                    os.remove(local_tmp)
                except OSError:
                    pass
            return ext, content

    return None, None


# ---------------------------------------------------------------------------
# ARQ jobs
# ---------------------------------------------------------------------------


async def upload_settlement_job(ctx: dict, settlement_id: int) -> dict:
    """ARQ job: upload one EmoneySettlement file by ID.

    Marks status UPLOADED on success. Transient failures raise arq.Retry —
    a plain exception ends the job on try 1 (ARQ only re-queues Retry), and
    one SFTP blip used to leave the file FAILED forever with no retry.
    """
    from arq import Retry

    from api.app.models.emoney_settlement import EmoneySettlement
    from api.database import AsyncSessionLocal
    from shared.config import get_settings

    settings = get_settings()

    if not settings.settlement_sftp_host:
        logger.warning("settlement_upload_no_host_configured", settlement_id=settlement_id)
        return {"status": "skipped", "reason": "no_sftp_host"}

    async with AsyncSessionLocal() as db:
        settlement = await db.get(EmoneySettlement, settlement_id)
        if settlement is None:
            logger.warning("settlement_upload_not_found", settlement_id=settlement_id)
            return {"status": "error", "reason": "not_found"}

        if settlement.status not in ("GENERATED", "FAILED"):
            logger.info(
                "settlement_upload_skip_state",
                settlement_id=settlement_id,
                status=settlement.status,
            )
            return {"status": "skipped", "reason": f"state={settlement.status}"}

        try:
            uploaded = await upload_settlement_file(
                file_path=settlement.file_path,
                host=settings.settlement_sftp_host,
                port=settings.settlement_sftp_port,
                username=settings.settlement_sftp_username,
                key_path=settings.settlement_sftp_key_path,
                known_hosts=settings.settlement_sftp_known_hosts or None,
                remote_dir=settings.settlement_sftp_remote_dir,
                connect_timeout=settings.settlement_sftp_connect_timeout,
            )
            if not uploaded:
                # Missing file on disk — do NOT mark UPLOADED. Leave it
                # GENERATED so the sweep keeps it visible instead of the
                # charge vanishing from the upload pipeline.
                raise FileNotFoundError(f"settlement file missing: {settlement.file_path}")
        except Exception as e:
            logger.error(
                "settlement_upload_failed",
                settlement_id=settlement_id,
                error=str(e),
            )
            settlement.status = "FAILED"
            await db.commit()
            job_try = ctx.get("job_try", 1)
            max_tries = ctx.get("max_tries", 3)
            if job_try < max_tries:
                raise Retry(defer=min(job_try * 30, 300)) from e
            # Exhausted in-job retries — the file stays FAILED and the
            # retry_stalled_settlements cron keeps re-enqueueing it hourly.
            from workers.background.alerting import enqueue_alert

            await enqueue_alert(
                ctx,
                key=f"settlement_upload_failed:{settlement_id}",
                message=(
                    f"<b>Settlement upload failed</b>\n\n"
                    f"File: <code>{settlement.filename}</code>\n"
                    f"Error: <code>{str(e)[:200]}</code>\n\n"
                    f"Auto-retry continues every 30m — check SFTP config and connectivity."
                ),
            )
            return {"status": "failed", "settlement_id": settlement_id, "error": str(e)}

        settlement.status = "UPLOADED"
        settlement.uploaded_at = datetime.now(UTC)
        await db.commit()

        logger.info("settlement_upload_job_done", settlement_id=settlement_id)
        return {"status": "success", "settlement_id": settlement_id}


async def retry_stalled_settlements(ctx: dict) -> dict:
    """ARQ cron: re-enqueue uploads for settlements stuck in GENERATED/FAILED.

    Closes the gaps ARQ retry alone can't: a crash between file commit and
    enqueue (job never existed) and retries exhausted after a long SFTP
    outage. The upload job's state check keeps this idempotent.
    """
    from sqlalchemy import select

    from api.app.models.emoney_settlement import EmoneySettlement
    from api.database import AsyncSessionLocal

    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    arq_redis = ctx.get("redis")
    if arq_redis is None or not hasattr(arq_redis, "enqueue_job"):
        return {"status": "skipped", "reason": "no_arq_redis"}

    requeued = 0
    async with AsyncSessionLocal() as db:
        stalled = await db.execute(
            select(EmoneySettlement).where(
                EmoneySettlement.status.in_(["GENERATED", "FAILED"]),
                EmoneySettlement.created_at < cutoff,
            )
        )
        for settlement in stalled.scalars():
            try:
                await arq_redis.enqueue_job(
                    "upload_settlement_job",
                    settlement.id,
                    _queue_name="arq:queue:background",
                )
                requeued += 1
            except Exception as e:
                logger.warning(
                    "settlement_sweep_enqueue_failed",
                    settlement_id=settlement.id,
                    error=str(e),
                )

    if requeued:
        logger.warning("settlement_sweep_requeued", count=requeued)
    return {"status": "success", "requeued": requeued}


async def poll_settlement_responses(ctx: dict) -> dict:
    """ARQ cron job: poll bank SFTP for .OK/.NOK responses on UPLOADED files.

    For each match: parse, set per-transaction bank_response_status, update
    settlement status to ACKED_OK / ACKED_NOK / PARTIAL.
    """
    from sqlalchemy import select

    from api.app.models.emoney_settlement import EmoneySettlement
    from api.app.models.emoney_transaction import EmoneyTransaction
    from api.database import AsyncSessionLocal
    from shared.config import get_settings

    settings = get_settings()
    if not settings.settlement_sftp_host:
        logger.info("settlement_poll_no_host_configured")
        return {"status": "skipped", "reason": "no_sftp_host"}

    cutoff = datetime.now(UTC) - timedelta(days=7)
    processed = 0
    acked_ok = 0
    acked_nok = 0
    partial = 0

    async with AsyncSessionLocal() as db:
        pending = await db.execute(
            select(EmoneySettlement)
            .where(
                EmoneySettlement.status == "UPLOADED",
                EmoneySettlement.uploaded_at.is_not(None),
                EmoneySettlement.uploaded_at >= cutoff,
            )
            .order_by(EmoneySettlement.uploaded_at)
        )
        for settlement in pending.scalars():
            try:
                ext, content = await fetch_response_file(
                    settlement_filename=settlement.filename,
                    host=settings.settlement_sftp_host,
                    port=settings.settlement_sftp_port,
                    username=settings.settlement_sftp_username,
                    key_path=settings.settlement_sftp_key_path,
                    known_hosts=settings.settlement_sftp_known_hosts or None,
                    remote_dir=settings.settlement_sftp_response_dir,
                    connect_timeout=settings.settlement_sftp_connect_timeout,
                )
            except Exception as e:
                logger.warning(
                    "settlement_poll_fetch_error",
                    settlement_id=settlement.id,
                    error=str(e),
                )
                continue

            if ext is None:
                continue

            parsed = (
                parse_ok_response(content) if ext == "OK" else parse_nok_response(content)
            )
            results = parsed["results"]

            # Build a lookup from settlement_payload_hex → status code.
            status_by_payload = {
                r["settlement_payload_hex"]: r["status"] for r in results
            }

            tx_rows = await db.execute(
                select(EmoneyTransaction).where(
                    EmoneyTransaction.settlement_batch_id == settlement.id
                )
            )
            ok_count = nok_count = 0
            resubmitted = 0
            now_utc = datetime.now(UTC)
            for tx in tx_rows.scalars():
                payload_key = (tx.settlement_payload_hex or "").upper()
                code = status_by_payload.get(payload_key)
                if code is None:
                    # Bank didn't enumerate this row; mark as response-missing.
                    code = "??"
                tx.bank_response_status = code
                tx.bank_response_at = now_utc
                if code in ("00", "02"):
                    # 02 = Duplicate Data: the bank already holds this record,
                    # so the money is accounted for — don't resend it forever.
                    ok_count += 1
                    continue
                nok_count += 1
                if code == "??":
                    continue  # unknown state — resending blindly could double-settle
                # Rejected: unlink so the next generation retries the charge.
                # Capped by retry_count — a payload the bank consistently
                # rejects (e.g. 01 invalid format) must not loop daily.
                if tx.retry_count < MAX_SETTLEMENT_RETRIES:
                    tx.retry_count += 1
                    tx.settlement_batch_id = None
                    resubmitted += 1
                else:
                    logger.error(
                        "settlement_tx_rejected_giving_up",
                        tx_id=tx.id,
                        bank_status=code,
                        bank_status_description=RESPONSE_STATUS_CODES.get(code, "Unknown"),
                        amount=tx.amount_deducted,
                        settlement_id=settlement.id,
                    )
                    from workers.background.alerting import enqueue_alert

                    await enqueue_alert(
                        ctx,
                        key=f"settlement_tx_rejected:{tx.id}",
                        message=(
                            f"<b>Settlement rejected by bank</b>\n\n"
                            f"Tx: <code>{tx.id}</code> — Rp {tx.amount_deducted:,}\n"
                            f"Bank status: <code>{code}</code> "
                            f"{RESPONSE_STATUS_CODES.get(code, 'Unknown')}\n"
                            f"Retries exhausted ({MAX_SETTLEMENT_RETRIES}). "
                            f"This charge needs manual follow-up with the bank."
                        ),
                    )

            if resubmitted:
                logger.warning(
                    "settlement_rows_unlinked_for_resubmit",
                    count=resubmitted,
                    settlement_id=settlement.id,
                )

            if ext == "NOK" or ok_count == 0:
                settlement.status = "ACKED_NOK"
                acked_nok += 1
            elif nok_count == 0:
                settlement.status = "ACKED_OK"
                acked_ok += 1
            else:
                settlement.status = "PARTIAL"
                partial += 1
            settlement.response_received_at = now_utc
            settlement.response_extension = ext

            processed += 1
            await db.commit()

    logger.info(
        "settlement_poll_done",
        processed=processed,
        acked_ok=acked_ok,
        acked_nok=acked_nok,
        partial=partial,
    )
    return {
        "status": "success",
        "processed": processed,
        "acked_ok": acked_ok,
        "acked_nok": acked_nok,
        "partial": partial,
    }



