"""Payment service — orchestrates cash, RFID, and e-money payments.

Business logic for processing payments at gate-out. This service:
1. Finds the active transaction (by barcode for cash/emoney, by card for RFID)
2. Calculates the tariff
3. Updates the transaction record
4. For e-money: arms a pending state for the gate; PASSTI tap result correlates by gate_id
"""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.models import Member
from api.app.services.shift_utils import get_current_shift
from api.app.services.snapshot_utils import enqueue_snapshots_for_gate
from api.app.services.transaction import (
    calculate_transaction_fee,
    complete_exit_transaction,
    find_active_transaction,
)
from shared.events import DeductStatus
from shared.logging import get_logger
from shared.redis import redis_client

logger = get_logger("payment_service")

EMONEY_PENDING_TTL_SECONDS = 180


def _emoney_pending_key(gate_id: str) -> str:
    return f"emoney:pending:{gate_id}"


async def _set_emoney_pending(gate_id: str, transaction_id: int, gate_out_id: int, fee: int) -> None:
    await redis_client.connect()
    await redis_client.set(
        _emoney_pending_key(gate_id),
        json.dumps({"transaction_id": transaction_id, "gate_out_id": gate_out_id, "fee": fee}),
        ex=EMONEY_PENDING_TTL_SECONDS,
    )


def _emoney_armed_tx_key(transaction_id: int) -> str:
    return f"emoney:armed_tx:{transaction_id}"


async def _claim_emoney_arm(transaction_id: int, gate_id: str) -> bool:
    """Claim the right to deduct for ``transaction_id`` at ``gate_id``.

    Two booths scanning the same ticket would otherwise both arm a deduct
    and the driver gets charged twice. SET NX makes exactly one claim win;
    re-arming at the SAME gate (operator retry after LOST_CONTACT) is
    allowed, a different gate is rejected until the claim expires or the
    result arrives.
    """
    await redis_client.connect()
    key = _emoney_armed_tx_key(transaction_id)
    acquired = await redis_client.set(key, gate_id, ex=EMONEY_PENDING_TTL_SECONDS, nx=True)
    if acquired:
        return True
    holder = await redis_client.get(key)
    if holder == gate_id:
        await redis_client.set(key, gate_id, ex=EMONEY_PENDING_TTL_SECONDS)  # refresh TTL
        return True
    return False


async def _release_emoney_arm(transaction_id: int) -> None:
    await redis_client.connect()
    await redis_client.delete(_emoney_armed_tx_key(transaction_id))


async def _get_emoney_pending(gate_id: str) -> dict | None:
    await redis_client.connect()
    raw = await redis_client.get(_emoney_pending_key(gate_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def _clear_emoney_pending(gate_id: str) -> None:
    await redis_client.connect()
    await redis_client.delete(_emoney_pending_key(gate_id))


async def _enqueue_print_receipt(db: AsyncSession, gate_id: str, transaction_data: dict) -> None:
    """Direct ARQ enqueue of exit receipt — bypasses gate_out daemon (attended exit).

    Skips enqueue if the gate's receipt_printer peripheral is disabled.
    """
    try:
        from sqlalchemy import select

        from api.app.models import Gate
        from shared.redis import get_arq_redis

        gate_result = await db.execute(select(Gate).where(Gate.code == gate_id))
        gate = gate_result.scalar_one_or_none()
        if gate is None or not gate.is_peripheral_enabled("receipt_printer"):
            logger.info("receipt_print_skipped_disabled", gate_id=gate_id)
            return

        arq_redis = await get_arq_redis()
        tx_id = transaction_data.get("transaction_id")
        await arq_redis.enqueue_job(
            "print_receipt",
            gate_id=gate_id,
            transaction_data=transaction_data,
            _job_id=f"receipt:{tx_id}" if tx_id else None,
        )
        logger.info("receipt_job_enqueued", gate_id=gate_id, transaction_id=tx_id)
    except Exception as e:
        logger.error("receipt_enqueue_failed", gate_id=gate_id, error=str(e))


# ---------------------------------------------------------------------------
# Cash Payment
# ---------------------------------------------------------------------------

async def process_cash_payment(
    db: AsyncSession,
    *,
    gate_id: str,
    gate_out_id: int,
    barcode: str | None = None,
    card_number: str | None = None,
    plate_number: str | None = None,
    paid_amount: int,
    operator_id: int | None = None,
    vehicle_type_id: int | None = None,
) -> dict:
    """Process a cash payment at gate-out.

    Args:
        db: Database session
        gate_id: Daemon gate ID (for Redis command)
        gate_out_id: Gate-out database ID
        barcode: Transaction barcode
        card_number: Transaction card number
        plate_number: Transaction plate number
        paid_amount: Amount received from driver
        operator_id: POS operator ID
        vehicle_type_id: Vehicle type override (mixed-lane operator selection)

    Returns:
        dict with transaction, fee, change_amount

    Raises:
        ValueError: If no active transaction found
    """
    tx = await find_active_transaction(
        db, barcode=barcode, card_number=card_number, plate_number=plate_number,
        for_update=True,
    )
    if tx is None:
        raise ValueError("No active transaction found")

    if vehicle_type_id is not None:
        tx.vehicle_type_id = vehicle_type_id
        await db.flush()

    await enqueue_snapshots_for_gate(db, gate_id, tx.id, "exit")

    fee = await calculate_transaction_fee(db, tx)

    # Trust boundary: never complete a cash exit for less than the fee.
    # ponytail: no partial-payment feature exists; add a partial path here if
    # one is ever introduced.
    if paid_amount < fee:
        raise ValueError(f"Insufficient payment: {paid_amount} < {fee}")

    shift = await get_current_shift(db)

    tx = await complete_exit_transaction(
        db,
        transaction=tx,
        gate_out_id=gate_out_id,
        payment_method="CASH",
        fee=fee,
        paid_amount=paid_amount,
        operator_id=operator_id,
        shift_id=shift.id if shift else None,
    )

    # Print receipt — direct ARQ (attended exit, no gate_out daemon)
    await _enqueue_print_receipt(
        db,
        gate_id,
        {
            "transaction_id": tx.id,
            "barcode": tx.barcode,
            "plate_number": tx.plate_number,
            "entry_time": tx.entry_time.isoformat() if tx.entry_time else None,
            "exit_time": tx.exit_time.isoformat() if tx.exit_time else None,
            "fee": fee,
            "paid_amount": paid_amount,
            "payment_method": "CASH",
        },
    )

    logger.info(
        "cash_payment_processed",
        transaction_id=tx.id,
        fee=fee,
        paid_amount=paid_amount,
        gate_id=gate_id,
    )

    return {
        "transaction": tx,
        "fee": fee,
        "change_amount": max(0, paid_amount - fee),
    }


# ---------------------------------------------------------------------------
# RFID Member Payment
# ---------------------------------------------------------------------------

async def process_rfid_payment(
    db: AsyncSession,
    *,
    gate_id: str,
    gate_out_id: int,
    card_number: str,
    operator_id: int | None = None,
) -> dict:
    """Process an RFID member payment at gate-out.

    Validates the member is active, finds the active transaction by card number,
    and completes it with zero fee.

    Args:
        db: Database session
        gate_id: Daemon gate ID
        gate_out_id: Gate-out database ID
        card_number: Member card number
        operator_id: POS operator ID

    Returns:
        dict with transaction, fee=0

    Raises:
        ValueError: If no active transaction or invalid member
    """
    from sqlalchemy import select

    # Validate member
    result = await db.execute(
        select(Member).where(
            Member.card_number == card_number,
            Member.is_active == True,  # noqa: E712
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise ValueError("Invalid or inactive member card")

    tx = await find_active_transaction(db, card_number=card_number, for_update=True)
    if tx is None:
        raise ValueError("No active transaction found for this card")

    await enqueue_snapshots_for_gate(db, gate_id, tx.id, "exit")

    shift = await get_current_shift(db)

    tx = await complete_exit_transaction(
        db,
        transaction=tx,
        gate_out_id=gate_out_id,
        payment_method="RFID_MEMBER",
        fee=0,
        member_id=member.id,
        operator_id=operator_id,
        shift_id=shift.id if shift else None,
    )

    # Attended exit: POS shows member info, operator opens gate via booth_bridge.

    logger.info(
        "rfid_payment_processed",
        transaction_id=tx.id,
        member_id=member.id,
        gate_id=gate_id,
    )

    return {
        "transaction": tx,
        "fee": 0,
        "member": member,
    }


# ---------------------------------------------------------------------------
# E-Money Payment
# ---------------------------------------------------------------------------

async def process_emoney_deduct(
    db: AsyncSession,
    *,
    gate_id: str,
    gate_out_id: int,
    barcode: str,
    vehicle_type_id: int | None = None,
    operator_id: int | None = None,
) -> dict:
    """Arm an e-money deduct at gate-out.

    Locates the active transaction by ticket barcode, computes the fee,
    and stores a pending state in Redis keyed by gate_id. The booth bridge
    will execute the deduct when the driver taps the PASSTI reader; the
    booth-result callback uses the pending state to correlate.

    Args:
        db: Database session
        gate_id: Booth gate ID
        gate_out_id: Gate-out database ID
        barcode: Ticket barcode
        vehicle_type_id: Vehicle type override for tariff calculation
        operator_id: POS operator ID

    Returns:
        dict with transaction, fee, status="ARMED"

    Raises:
        ValueError: If no active transaction found
    """
    tx = await find_active_transaction(db, barcode=barcode, for_update=True)
    if tx is None:
        raise ValueError("No active transaction found for this ticket")

    if vehicle_type_id is not None:
        tx.vehicle_type_id = vehicle_type_id
        await db.flush()

    fee = await calculate_transaction_fee(db, tx)

    # Cross-booth double-deduct guard: only one gate may arm a deduct per
    # transaction (same-gate re-arm for retries stays allowed).
    if not await _claim_emoney_arm(tx.id, gate_id):
        raise ValueError("Pembayaran e-money sedang berjalan di gate lain")

    await _set_emoney_pending(gate_id, tx.id, gate_out_id, fee)

    # DB-level in-flight marker: lets timeout_pending_payments recover stuck
    # arms (it queries payment_method='PENDING') and shows the POS state.
    tx.payment_method = "PENDING"
    await db.flush()

    logger.info(
        "emoney_deduct_armed",
        transaction_id=tx.id,
        fee=fee,
        barcode=barcode,
        gate_id=gate_id,
    )

    return {
        "transaction": tx,
        "fee": fee,
        "status": "ARMED",
    }


async def _resolve_emoney_reader(db: AsyncSession, mid: str | None, tid: str | None):
    """Link a deduct to its configured reader for settlement grouping.

    Matches MID+TID from the PASSTI response against admin-configured
    readers (case-insensitive). Falls back to the single active reader when
    exactly one is configured — the standard one-reader booth — so
    settlement isn't silently skipped over a formatting mismatch. Returns
    None (and logs) when ambiguous; those rows are excluded from files and
    the error log makes the gap visible.
    """
    from sqlalchemy import func, select

    from api.app.models import EmoneyReader

    if mid or tid:
        q = select(EmoneyReader).where(EmoneyReader.is_active == True)  # noqa: E712
        if mid:
            q = q.where(func.upper(EmoneyReader.mid) == mid.upper())
        if tid:
            q = q.where(func.upper(EmoneyReader.tid) == tid.upper())
        reader = (await db.execute(q)).scalar_one_or_none()
        if reader is not None:
            return reader

    count = (
        await db.execute(
            select(func.count(EmoneyReader.id)).where(EmoneyReader.is_active == True)  # noqa: E712
        )
    ).scalar_one()
    if count == 1:
        reader = (
            await db.execute(
                select(EmoneyReader).where(EmoneyReader.is_active == True)  # noqa: E712
            )
        ).scalar_one()
        logger.warning(
            "emoney_reader_matched_by_fallback",
            mid=mid,
            tid=tid,
            reader_id=reader.id,
        )
        return reader

    logger.error(
        "emoney_reader_unresolved_excluded_from_settlement",
        mid=mid,
        tid=tid,
        active_readers=count,
    )
    return None


async def process_emoney_result(
    db: AsyncSession,
    *,
    gate_id: str,
    gate_out_id: int,
    card_number: str,
    status: DeductStatus,
    deduct_amount: int,
    balance_before: int,
    balance_after: int,
    transaction_counter: int,
    raw_response_hex: str,
    settlement_payload_hex: str = "",
    card_type: str | None = None,
    card_type_code: int | None = None,
    mid: str | None = None,
    tid: str | None = None,
    transaction_id: int | None = None,
    operator_id: int | None = None,
) -> dict:
    """Process the result of an e-money deduct operation.

    Correlation: prefers the explicit ``transaction_id`` echoed back by the
    booth bridge (survives Redis pending expiry / outbox replay), falling
    back to the Redis pending state armed at deduct time.

    Idempotent: a duplicate delivery (bridge retry, POS confirm racing the
    bridge) returns the already-recorded result instead of erroring, and a
    late SUCCESS for a transaction that completed another way still records
    the EmoneyTransaction so the charge reaches settlement.

    Args:
        db: Database session
        gate_id: Daemon gate ID
        gate_out_id: Gate-out database ID
        card_number: E-money card number
        status: Deduct result status
        deduct_amount: Amount deducted
        balance_before: Balance before deduction
        balance_after: Balance after deduction
        transaction_counter: PASSTI transaction counter
        raw_response_hex: Raw PASSTI response
        settlement_payload_hex: Deduct body (cardtype..CardLog) for settlement
        mid/tid: Reader identifiers from the deduct response
        transaction_id: Parking transaction armed for this deduct
        operator_id: POS operator ID

    Returns:
        dict with transaction, emoney_transaction_id, success bool
    """
    from sqlalchemy import select

    from api.app.models import EmoneyTransaction, ParkingTransaction

    pending = await _get_emoney_pending(gate_id)
    tx_id = transaction_id or (pending["transaction_id"] if pending else None)
    if tx_id is None:
        raise ValueError("No pending e-money deduct for this gate (timeout or never armed)")

    # Bound the FOR UPDATE wait: if another booth-result is mid-flight on the
    # same row, fail fast instead of holding the connection (and blocking all
    # other payment ops) until the slow path commits.
    await db.execute(text("SET LOCAL lock_timeout = '3s'"))
    tx = await db.get(ParkingTransaction, tx_id, with_for_update=True)
    if tx is None:
        raise ValueError("Pending transaction missing or already completed")

    if tx.status != "ACTIVE":
        # Duplicate delivery or a late result: if this exact deduct was
        # already recorded, return it as success (idempotent replay).
        existing = (
            await db.execute(
                select(EmoneyTransaction).where(
                    EmoneyTransaction.parking_transaction_id == tx.id,
                    EmoneyTransaction.card_number == card_number,
                    EmoneyTransaction.transaction_counter == transaction_counter,
                )
            )
        ).scalars().first()
        if existing is not None:
            await _clear_emoney_pending(gate_id)
            await _release_emoney_arm(tx.id)
            logger.info(
                "emoney_result_duplicate_ignored",
                transaction_id=tx.id,
                emoney_transaction_id=existing.id,
                gate_id=gate_id,
            )
            return {
                "transaction": tx,
                "emoney_transaction_id": existing.id,
                "success": existing.status == "SUCCESS",
                "status": existing.status,
                "is_intermediate": False,
            }
        # SUCCESS landing after cash/RFID fallback: the card WAS debited.
        # Record it (settlement must collect it) and flag loudly — ops owes
        # the driver a refund.
        if status in (DeductStatus.SUCCESS, DeductStatus.CORRECTION_VERIFIED):
            late_reader = await _resolve_emoney_reader(db, mid, tid)
            emoney_tx = EmoneyTransaction(
                parking_transaction_id=tx.id,
                emoney_reader_id=late_reader.id if late_reader else None,
                card_number=card_number,
                card_type=card_type,
                card_type_code=card_type_code,
                amount_deducted=deduct_amount,
                balance_before=balance_before,
                balance_after=balance_after,
                transaction_counter=transaction_counter,
                raw_response_hex=raw_response_hex,
                settlement_payload_hex=settlement_payload_hex or None,
                status=status.value,
            )
            db.add(emoney_tx)
            await db.flush()
            await db.refresh(emoney_tx)
            await _clear_emoney_pending(gate_id)
            await _release_emoney_arm(tx.id)
            logger.error(
                "emoney_late_success_after_completion_refund_owed",
                transaction_id=tx.id,
                emoney_transaction_id=emoney_tx.id,
                tx_status=tx.status,
                payment_method=tx.payment_method,
                deduct_amount=deduct_amount,
                gate_id=gate_id,
            )
            return {
                "transaction": tx,
                "emoney_transaction_id": emoney_tx.id,
                "success": False,
                "status": status.value,
                "is_intermediate": False,
            }
        raise ValueError("Pending transaction missing or already completed")

    # Persist the card_number on the parking transaction now that we know which card paid.
    if card_number:
        tx.card_number = card_number
        await db.flush()

    success = status in (DeductStatus.SUCCESS, DeductStatus.CORRECTION_VERIFIED)
    is_intermediate = status == DeductStatus.LOST_CONTACT
    is_terminal_failure = status in (
        DeductStatus.FAILED,
        DeductStatus.WRONG_CARD,
        DeductStatus.INSUFFICIENT_BALANCE,
        DeductStatus.CORRECTION_FAILED,
    )

    # Server-truth fee: the amount armed at deduct time. The hardware debit
    # (deduct_amount) is what actually left the card — they should match;
    # a mismatch means a stale/tampered client amount and must be visible.
    armed_fee = pending.get("fee") if pending else None
    if armed_fee is not None and deduct_amount != armed_fee and success:
        logger.error(
            "emoney_fee_mismatch_armed_vs_deducted",
            transaction_id=tx.id,
            armed_fee=armed_fee,
            deduct_amount=deduct_amount,
            gate_id=gate_id,
        )

    reader = None
    if success or is_intermediate:
        reader = await _resolve_emoney_reader(db, mid, tid)

    # Create EmoneyTransaction record
    emoney_tx = EmoneyTransaction(
        parking_transaction_id=tx.id,
        emoney_reader_id=reader.id if reader else None,
        card_number=card_number,
        card_type=card_type,
        card_type_code=card_type_code,
        amount_deducted=deduct_amount,
        balance_before=balance_before,
        balance_after=balance_after,
        transaction_counter=transaction_counter,
        raw_response_hex=raw_response_hex,
        settlement_payload_hex=settlement_payload_hex or None,
        status=status.value,
    )
    db.add(emoney_tx)
    await db.flush()
    await db.refresh(emoney_tx)

    if success:
        shift = await get_current_shift(db)
        # Prefer gate_out_id from pending state (set at arm time) over the
        # one the booth bridge echoes back.
        effective_gate_out_id = (pending or {}).get("gate_out_id") or gate_out_id

        tx = await complete_exit_transaction(
            db,
            transaction=tx,
            gate_out_id=effective_gate_out_id,
            payment_method="EMONEY",
            fee=deduct_amount,
            paid_amount=deduct_amount,
            emoney_transaction_id=emoney_tx.id,
            operator_id=operator_id,
            shift_id=shift.id if shift else None,
        )

        await _clear_emoney_pending(gate_id)
        await _release_emoney_arm(tx.id)
        await enqueue_snapshots_for_gate(db, gate_id, tx.id, "exit")

        # Attended exit: POS shows payment result, operator opens gate via booth_bridge.
        await _enqueue_print_receipt(
            db,
            gate_id,
            {
                "transaction_id": tx.id,
                "barcode": tx.barcode,
                "plate_number": tx.plate_number,
                "entry_time": tx.entry_time.isoformat() if tx.entry_time else None,
                "exit_time": tx.exit_time.isoformat() if tx.exit_time else None,
                "fee": deduct_amount,
                "paid_amount": deduct_amount,
                "payment_method": "EMONEY",
                "balance_after": balance_after,
            },
        )

        logger.info(
            "emoney_payment_success",
            transaction_id=tx.id,
            emoney_transaction_id=emoney_tx.id,
            fee=deduct_amount,
            gate_id=gate_id,
            status=status.value,
        )

    elif is_intermediate:
        # LOST_CONTACT: keep pending + arm so operator can ask driver to re-tap same card.
        logger.warning(
            "emoney_lost_contact",
            transaction_id=tx.id,
            emoney_transaction_id=emoney_tx.id,
            gate_id=gate_id,
        )

    elif is_terminal_failure or status == DeductStatus.TIMEOUT:
        # Clear pending + arm; transaction stays ACTIVE so operator can fall back to cash.
        await _clear_emoney_pending(gate_id)
        await _release_emoney_arm(tx.id)
        tx.payment_method = None
        tx.fee = None
        await db.flush()
        logger.warning(
            "emoney_payment_failed",
            transaction_id=tx.id,
            emoney_transaction_id=emoney_tx.id,
            status=status.value,
            gate_id=gate_id,
        )

    return {
        "transaction": tx,
        "emoney_transaction_id": emoney_tx.id,
        "success": success,
        "status": status.value,
        "is_intermediate": is_intermediate,
    }
