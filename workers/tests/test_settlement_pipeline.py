"""Settlement upload, response polling and stalled-retry pipeline tests.

The bank SFTP is replaced by an in-process fake; everything else (DB rows,
status transitions, per-transaction reconciliation, retry caps) is real.
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models.emoney_settlement import EmoneySettlement
from api.app.models.emoney_transaction import EmoneyTransaction
from workers.background import settlement_uploader as up


class _SessionCtx:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *exc) -> None:
        return None


def _settings(**overrides) -> SimpleNamespace:
    base = {
        "settlement_sftp_host": "bank.example",
        "settlement_sftp_port": 22,
        "settlement_sftp_username": "parking",
        "settlement_sftp_key_path": "/tmp/key",
        "settlement_sftp_known_hosts": None,
        "settlement_sftp_remote_dir": "/out",
        "settlement_sftp_response_dir": "/response",
        "settlement_sftp_connect_timeout": 5,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch_session_and_settings(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr("api.database.AsyncSessionLocal", lambda: _SessionCtx(db_session))
    monkeypatch.setattr("shared.config.get_settings", lambda: _settings())
    yield


async def _settlement(
    db: AsyncSession,
    tmp_path,
    *,
    status: str = "GENERATED",
    filename: str = "settlement.txt",
    created_at: datetime | None = None,
    uploaded_at: datetime | None = None,
) -> EmoneySettlement:
    path = tmp_path / filename
    path.write_text("01001\npayload\n", encoding="ascii")
    row = EmoneySettlement(
        filename=filename,
        file_path=str(path),
        batch_date=date.today(),
        batch_number=1,
        total_transactions=1,
        total_amount=500,
        status=status,
        uploaded_at=uploaded_at,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _tx(db: AsyncSession, settlement_id: int | None, payload_hex: str = "ABCD"):
    row = EmoneyTransaction(
        card_number="5712017101900004",
        card_type="Mandiri eMoney",
        amount_deducted=500,
        balance_before=9200,
        balance_after=8700,
        status="SUCCESS",
        settlement_payload_hex=payload_hex,
        settlement_batch_id=settlement_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


class TestUploadJob:
    async def test_success_marks_uploaded(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(db_session, tmp_path)
        upload = AsyncMock(return_value=True)
        monkeypatch.setattr(up, "upload_settlement_file", upload)

        result = await up.upload_settlement_job({"job_try": 1}, settlement.id)

        assert result["status"] == "success"
        await db_session.refresh(settlement)
        assert settlement.status == "UPLOADED"
        assert settlement.uploaded_at is not None
        upload.assert_awaited_once()

    async def test_transient_failure_raises_retry(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(db_session, tmp_path)
        monkeypatch.setattr(
            up, "upload_settlement_file", AsyncMock(side_effect=OSError("sftp down"))
        )

        with pytest.raises(Retry):
            await up.upload_settlement_job({"job_try": 1, "max_tries": 3}, settlement.id)

        await db_session.refresh(settlement)
        assert settlement.status == "FAILED"

    async def test_exhausted_retries_alert_and_fail(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(db_session, tmp_path)
        monkeypatch.setattr(
            up, "upload_settlement_file", AsyncMock(side_effect=OSError("sftp down"))
        )
        alert = AsyncMock()
        monkeypatch.setattr("workers.background.alerting.enqueue_alert", alert)

        result = await up.upload_settlement_job(
            {"job_try": 3, "max_tries": 3}, settlement.id
        )

        assert result["status"] == "failed"
        alert.assert_awaited_once()
        await db_session.refresh(settlement)
        assert settlement.status == "FAILED"

    async def test_missing_local_file_marks_failed(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(db_session, tmp_path)
        monkeypatch.setattr(up, "upload_settlement_file", AsyncMock(return_value=False))

        with pytest.raises(Retry):
            await up.upload_settlement_job({"job_try": 1, "max_tries": 3}, settlement.id)

        await db_session.refresh(settlement)
        assert settlement.status == "FAILED"

    async def test_non_uploadable_state_is_skipped(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(db_session, tmp_path, status="ACKED_OK")
        upload = AsyncMock()
        monkeypatch.setattr(up, "upload_settlement_file", upload)

        result = await up.upload_settlement_job({}, settlement.id)

        assert result["status"] == "skipped"
        upload.assert_not_called()


class TestStalledSweep:
    async def test_requeues_only_old_generated_or_failed(
        self, db_session: AsyncSession, tmp_path
    ):
        old = datetime.now(UTC) - timedelta(minutes=30)
        stale_generated = await _settlement(
            db_session, tmp_path, filename="a.txt", status="GENERATED", created_at=old
        )
        stale_failed = await _settlement(
            db_session, tmp_path, filename="b.txt", status="FAILED", created_at=old
        )
        fresh = await _settlement(
            db_session, tmp_path, filename="c.txt", status="GENERATED"
        )
        acked = await _settlement(
            db_session, tmp_path, filename="d.txt", status="UPLOADED", created_at=old
        )

        arq = SimpleNamespace(enqueue_job=AsyncMock())
        result = await up.retry_stalled_settlements({"redis": arq})

        assert result == {"status": "success", "requeued": 2}
        queued_ids = {call.args[1] for call in arq.enqueue_job.await_args_list}
        assert queued_ids == {stale_generated.id, stale_failed.id}
        assert fresh.id not in queued_ids
        assert acked.id not in queued_ids

    async def test_without_arq_is_skipped(self):
        result = await up.retry_stalled_settlements({})
        assert result["status"] == "skipped"


class TestResponsePoll:
    async def test_ok_response_marks_acked(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(
            db_session,
            tmp_path,
            status="UPLOADED",
            uploaded_at=datetime.now(UTC),
        )
        tx = await _tx(db_session, settlement.id, payload_hex="ABCD")
        content = f"01001\n{tx.settlement_payload_hex}00\n"
        monkeypatch.setattr(
            up, "fetch_response_file", AsyncMock(return_value=("OK", content))
        )

        result = await up.poll_settlement_responses({})

        assert result["acked_ok"] == 1
        await db_session.refresh(settlement)
        await db_session.refresh(tx)
        assert settlement.status == "ACKED_OK"
        assert settlement.response_extension == "OK"
        assert tx.bank_response_status == "00"

    async def test_duplicate_status_counts_as_accepted(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(
            db_session,
            tmp_path,
            status="UPLOADED",
            uploaded_at=datetime.now(UTC),
        )
        tx = await _tx(db_session, settlement.id, payload_hex="ABCD")
        content = f"01001\n{tx.settlement_payload_hex}02\n"
        monkeypatch.setattr(
            up, "fetch_response_file", AsyncMock(return_value=("OK", content))
        )

        await up.poll_settlement_responses({})

        await db_session.refresh(settlement)
        await db_session.refresh(tx)
        assert settlement.status == "ACKED_OK"
        assert tx.settlement_batch_id == settlement.id

    async def test_partial_response_unlinks_rejected_for_resubmit(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(
            db_session,
            tmp_path,
            status="UPLOADED",
            uploaded_at=datetime.now(UTC),
        )
        accepted = await _tx(db_session, settlement.id, payload_hex="AAAA")
        rejected = await _tx(db_session, settlement.id, payload_hex="BBBB")
        content = (
            "01002\n"
            f"{accepted.settlement_payload_hex}00\n"
            f"{rejected.settlement_payload_hex}01\n"
        )
        monkeypatch.setattr(
            up, "fetch_response_file", AsyncMock(return_value=("OK", content))
        )

        await up.poll_settlement_responses({})

        await db_session.refresh(settlement)
        await db_session.refresh(rejected)
        assert settlement.status == "PARTIAL"
        assert rejected.settlement_batch_id is None
        assert rejected.retry_count == 1
        assert rejected.bank_response_status == "01"

    async def test_rejected_row_at_retry_cap_alerts(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(
            db_session,
            tmp_path,
            status="UPLOADED",
            uploaded_at=datetime.now(UTC),
        )
        rejected = await _tx(db_session, settlement.id, payload_hex="CCCC")
        rejected.retry_count = 3
        await db_session.commit()
        content = f"01001\n{rejected.settlement_payload_hex}01\n"
        monkeypatch.setattr(
            up, "fetch_response_file", AsyncMock(return_value=("NOK", content))
        )
        alert = AsyncMock()
        monkeypatch.setattr("workers.background.alerting.enqueue_alert", alert)

        await up.poll_settlement_responses({})

        await db_session.refresh(settlement)
        await db_session.refresh(rejected)
        assert settlement.status == "ACKED_NOK"
        assert rejected.settlement_batch_id == settlement.id
        assert rejected.retry_count == 3
        alert.assert_awaited_once()

    async def test_missing_response_leaves_uploaded(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        settlement = await _settlement(
            db_session,
            tmp_path,
            status="UPLOADED",
            uploaded_at=datetime.now(UTC),
        )
        monkeypatch.setattr(
            up, "fetch_response_file", AsyncMock(return_value=(None, None))
        )

        result = await up.poll_settlement_responses({})

        assert result["processed"] == 0
        await db_session.refresh(settlement)
        assert settlement.status == "UPLOADED"
