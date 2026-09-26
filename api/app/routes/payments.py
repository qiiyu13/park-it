"""Payment routes."""

import json

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.api_key import require_api_key
from api.app.middleware.auth import require_operator
from api.app.middleware.metrics import payment_attempts_total, payment_success_total
from api.app.schemas.payment import (
    CalculateFeeRequest,
    CalculateFeeResponse,
    CashPaymentRequest,
    EmoneyDeductRequest,
    EmoneyResultRequest,
    PaymentResponse,
    RfidPaymentRequest,
    TransactionLookupRequest,
    TransactionLookupResponse,
)
from api.app.services.payment import (
    process_cash_payment,
    process_emoney_deduct,
    process_emoney_result,
    process_rfid_payment,
)
from api.app.services.rate_limit_booth import enforce_booth_rate_limit
from api.app.services.transaction import calculate_transaction_fee, find_active_transaction
from api.database import get_db
from shared.events import DeductStatus
from shared.logging import get_logger
from shared.redis import redis_client

logger = get_logger("payment_routes")

router = APIRouter(prefix="/payments", tags=["Payments"])

IDEMPOTENCY_TTL = 300  # 5 minutes


async def _check_idempotency(idempotency_key: str | None) -> PaymentResponse | None:
    """Check if a payment with this idempotency key was already processed."""
    if not idempotency_key:
        return None
    try:
        await redis_client.connect()
        cached = await redis_client.get(f"idempotency:{idempotency_key}")
        if cached:
            return PaymentResponse(**json.loads(cached))
    except Exception as e:
        # Availability over dedup: without Redis the payment still has the DB
        # row lock; failing closed would block the exit lane entirely.
        logger.warning("idempotency_check_unavailable", error=str(e))
    return None


async def _store_idempotency(idempotency_key: str | None, response: PaymentResponse) -> None:
    """Cache a payment response for idempotency deduplication.

    SET NX closes the check-then-act race: two concurrent requests with the
    same key — only the first writes, and the loser reads the winner's cached
    response on its next attempt.
    """
    if not idempotency_key:
        return
    try:
        await redis_client.connect()
        await redis_client.set(
            f"idempotency:{idempotency_key}",
            response.model_dump_json(),
            ex=IDEMPOTENCY_TTL,
            nx=True,
        )
    except Exception as e:
        logger.warning("idempotency_store_failed", error=str(e))


def _get_operator_id(user: dict) -> int | None:
    """Extract operator ID from JWT payload."""
    sub = user.get("sub")
    return int(sub) if sub else None


@router.post("/cash", response_model=PaymentResponse)
async def cash_payment(
    request: Request,
    payment: CashPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> PaymentResponse:
    """Process cash payment and open gate."""
    cached = await _check_idempotency(x_idempotency_key)
    if cached:
        return cached

    payment_attempts_total.labels(method="cash").inc()
    try:
        result = await process_cash_payment(
            db,
            gate_id=payment.gate_id,
            gate_out_id=payment.gate_out_id,
            barcode=payment.barcode,
            plate_number=payment.plate_number,
            paid_amount=payment.paid_amount,
            operator_id=_get_operator_id(user),
            vehicle_type_id=payment.vehicle_type_id,
        )
        payment_success_total.labels(method="cash").inc()
        resp = PaymentResponse(
            success=True,
            message="Payment successful. Receipt printed.",
            transaction_id=result["transaction"].id,
            fee=result["fee"],
            change_amount=result["change_amount"],
            payment_method="CASH",
            receipt_queued=True,
        )
        await _store_idempotency(x_idempotency_key, resp)
        return resp
    except ValueError as e:
        logger.warning("cash_payment_failed", error=str(e), gate_id=payment.gate_id)
        return PaymentResponse(
            success=False,
            message=str(e),
        )


@router.post("/rfid", response_model=PaymentResponse)
async def rfid_payment(
    request: Request,
    payment: RfidPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> PaymentResponse:
    """Process RFID member payment and open gate."""
    cached = await _check_idempotency(x_idempotency_key)
    if cached:
        return cached

    payment_attempts_total.labels(method="rfid").inc()
    try:
        result = await process_rfid_payment(
            db,
            gate_id=payment.gate_id,
            gate_out_id=payment.gate_out_id,
            card_number=payment.card_number,
            operator_id=_get_operator_id(user),
        )
        payment_success_total.labels(method="rfid").inc()
        resp = PaymentResponse(
            success=True,
            message="RFID payment successful",
            transaction_id=result["transaction"].id,
            fee=0,
            change_amount=0,
            payment_method="RFID_MEMBER",
        )
        await _store_idempotency(x_idempotency_key, resp)
        return resp
    except ValueError as e:
        logger.warning("rfid_payment_failed", error=str(e), gate_id=payment.gate_id)
        return PaymentResponse(
            success=False,
            message=str(e),
        )


@router.post("/emoney/deduct", response_model=PaymentResponse)
async def emoney_deduct(
    request: Request,
    payment: EmoneyDeductRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
) -> PaymentResponse:
    """Initiate e-money deduct. Daemon will publish result via Pub/Sub."""
    payment_attempts_total.labels(method="emoney").inc()
    try:
        result = await process_emoney_deduct(
            db,
            gate_id=payment.gate_id,
            gate_out_id=payment.gate_out_id,
            barcode=payment.barcode,
            vehicle_type_id=payment.vehicle_type_id,
            operator_id=_get_operator_id(user),
        )
        payment_success_total.labels(method="emoney").inc()
        return PaymentResponse(
            success=True,
            message="Tempel kartu untuk pembayaran",
            transaction_id=result["transaction"].id,
            fee=result["fee"],
            payment_method="PENDING",
        )
    except ValueError as e:
        logger.warning("emoney_deduct_failed", error=str(e), gate_id=payment.gate_id)
        return PaymentResponse(
            success=False,
            message=str(e),
        )


@router.post("/emoney/result", response_model=PaymentResponse)
async def emoney_result(
    request: Request,
    result: EmoneyResultRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
) -> PaymentResponse:
    """Process e-money deduct result (called by event handler or manually)."""
    try:
        status_enum = DeductStatus(result.status)
    except ValueError:
        return PaymentResponse(
            success=False,
            message=f"Invalid deduct status: {result.status}",
        )

    try:
        proc_result = await process_emoney_result(
            db,
            gate_id=result.gate_id,
            gate_out_id=result.gate_out_id,
            transaction_id=result.transaction_id,
            card_number=result.card_number,
            status=status_enum,
            deduct_amount=result.deduct_amount,
            balance_before=result.balance_before,
            balance_after=result.balance_after,
            transaction_counter=result.transaction_counter,
            raw_response_hex=result.raw_response_hex,
            settlement_payload_hex=result.settlement_payload_hex,
            card_type=result.card_type,
            card_type_code=result.card_type_code,
            mid=result.mid,
            tid=result.tid,
            operator_id=_get_operator_id(user),
        )
        return PaymentResponse(
            success=proc_result["success"],
            message="E-money payment processed" if proc_result["success"] else "E-money payment failed",
            transaction_id=proc_result["transaction"].id,
            fee=result.deduct_amount if proc_result["success"] else None,
            payment_method="EMONEY" if proc_result["success"] else None,
        )
    except ValueError as e:
        logger.warning("emoney_result_failed", error=str(e), gate_id=result.gate_id)
        return PaymentResponse(
            success=False,
            message=str(e),
        )


@router.post("/rfid/booth", response_model=PaymentResponse)
async def rfid_booth(
    request: Request,
    payment: RfidPaymentRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> PaymentResponse:
    """Process RFID member exit triggered by booth_bridge UHF reader (machine-to-machine)."""
    await enforce_booth_rate_limit(payment.gate_id)
    payment_attempts_total.labels(method="rfid").inc()
    try:
        result = await process_rfid_payment(
            db,
            gate_id=payment.gate_id,
            gate_out_id=payment.gate_out_id,
            card_number=payment.card_number,
            operator_id=None,
        )
        payment_success_total.labels(method="rfid").inc()
        return PaymentResponse(
            success=True,
            message="RFID payment successful",
            transaction_id=result["transaction"].id,
            fee=0,
            change_amount=0,
            payment_method="RFID_MEMBER",
        )
    except ValueError as e:
        logger.warning("rfid_booth_failed", error=str(e), gate_id=payment.gate_id)
        return PaymentResponse(success=False, message=str(e))


@router.post("/emoney/booth-result", response_model=PaymentResponse)
async def emoney_booth_result(
    request: Request,
    result: EmoneyResultRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> PaymentResponse:
    """Process e-money deduct result from booth bridge (machine-to-machine)."""
    await enforce_booth_rate_limit(result.gate_id)
    try:
        status_enum = DeductStatus(result.status)
    except ValueError:
        return PaymentResponse(
            success=False,
            message=f"Invalid deduct status: {result.status}",
        )

    try:
        proc_result = await process_emoney_result(
            db,
            gate_id=result.gate_id,
            gate_out_id=result.gate_out_id,
            transaction_id=result.transaction_id,
            card_number=result.card_number,
            status=status_enum,
            deduct_amount=result.deduct_amount,
            balance_before=result.balance_before,
            balance_after=result.balance_after,
            transaction_counter=result.transaction_counter,
            raw_response_hex=result.raw_response_hex,
            settlement_payload_hex=result.settlement_payload_hex,
            card_type=result.card_type,
            card_type_code=result.card_type_code,
            mid=result.mid,
            tid=result.tid,
            operator_id=None,
        )
        return PaymentResponse(
            success=proc_result["success"],
            message="E-money payment processed" if proc_result["success"] else "E-money payment failed",
            transaction_id=proc_result["transaction"].id,
            fee=result.deduct_amount if proc_result["success"] else None,
            payment_method="EMONEY" if proc_result["success"] else None,
        )
    except ValueError as e:
        logger.warning("emoney_booth_result_failed", error=str(e), gate_id=result.gate_id)
        return PaymentResponse(success=False, message=str(e))


@router.post("/lookup", response_model=TransactionLookupResponse)
async def lookup_transaction(
    request: Request,
    lookup: TransactionLookupRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
) -> TransactionLookupResponse:
    """Look up an active transaction by barcode, card, or plate."""
    tx = await find_active_transaction(
        db,
        barcode=lookup.barcode,
        card_number=lookup.card_number,
        plate_number=lookup.plate_number,
    )
    if tx is None:
        return TransactionLookupResponse(found=False)

    fee = await calculate_transaction_fee(db, tx, vehicle_type_id_override=lookup.vehicle_type_id)

    return TransactionLookupResponse(
        found=True,
        transaction={
            "id": tx.id,
            "barcode": tx.barcode,
            "card_number": tx.card_number,
            "plate_number": tx.plate_number,
            "entry_time": tx.entry_time.isoformat() if tx.entry_time else None,
            "vehicle_type_id": tx.vehicle_type_id,
            "gate_in_id": tx.gate_in_id,
            "payment_method": tx.payment_method,
        },
        fee=fee,
    )


@router.post("/calculate-fee", response_model=CalculateFeeResponse)
async def calculate_fee_endpoint(
    req: CalculateFeeRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
) -> CalculateFeeResponse:
    """Recalculate fee for an active transaction with optional vehicle type override."""
    from api.app.models import ParkingTransaction

    tx = await db.get(ParkingTransaction, req.transaction_id)
    if tx is None or tx.status != "ACTIVE":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Active transaction not found")

    fee = await calculate_transaction_fee(db, tx, vehicle_type_id_override=req.vehicle_type_id)
    effective_vt_id = req.vehicle_type_id if req.vehicle_type_id is not None else tx.vehicle_type_id
    return CalculateFeeResponse(fee=fee, vehicle_type_id=effective_vt_id)
