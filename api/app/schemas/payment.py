"""Payment Pydantic schemas."""

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Requests
# =============================================================================

class CashPaymentRequest(BaseModel):
    """Cash payment confirmation request."""

    gate_id: str = Field(..., description="Daemon gate ID")
    gate_out_id: int = Field(..., description="Gate-out database ID")
    transaction_id: int | None = Field(None, description="Transaction ID (optional)")
    barcode: str | None = Field(None, description="Ticket barcode")
    plate_number: str | None = Field(None, description="License plate")
    paid_amount: int = Field(..., ge=0, description="Amount received from driver")
    vehicle_type_id: int | None = Field(None, description="Vehicle type override for tariff calculation")


class RfidPaymentRequest(BaseModel):
    """RFID member payment request."""

    gate_id: str = Field(..., description="Daemon gate ID")
    gate_out_id: int = Field(..., description="Gate-out database ID")
    card_number: str = Field(..., min_length=4, max_length=32, description="Member card number")


class EmoneyDeductRequest(BaseModel):
    """E-money deduct arm request — operator scanned ticket, ready for driver tap."""

    gate_id: str = Field(..., description="Booth gate ID")
    gate_out_id: int = Field(..., description="Gate-out database ID")
    barcode: str = Field(..., min_length=4, max_length=64, description="Ticket barcode")
    vehicle_type_id: int | None = Field(None, description="Vehicle type override for tariff calculation")


class EmoneyResultRequest(BaseModel):
    """E-money deduct result callback (internal event handler or booth bridge)."""

    gate_id: str = Field(..., description="Daemon gate ID")
    gate_out_id: int = Field(..., description="Gate-out database ID")
    transaction_id: int | None = Field(
        default=None,
        description="Parking transaction armed for this deduct — primary correlation",
    )
    card_number: str = Field(..., min_length=4, max_length=32, description="E-money card number")
    card_type: str | None = Field(default=None, description="Card type name")
    card_type_code: int | None = Field(default=None, ge=0, le=255, description="PASSTI card type code")
    status: str = Field(..., description="Deduct result status")
    deduct_amount: int = Field(..., ge=0)
    balance_before: int = Field(..., ge=0)
    balance_after: int = Field(..., ge=0)
    transaction_counter: int = Field(..., ge=0)
    raw_response_hex: str = Field(default="")
    settlement_payload_hex: str = Field(default="")
    mid: str | None = Field(default=None, description="Reader MID from deduct response")
    tid: str | None = Field(default=None, description="Reader TID from deduct response")


class TransactionLookupRequest(BaseModel):
    """Lookup an active transaction."""

    barcode: str | None = None
    card_number: str | None = None
    plate_number: str | None = None
    vehicle_type_id: int | None = None


class CalculateFeeRequest(BaseModel):
    """Fee recalculation request (for vehicle type override)."""

    transaction_id: int = Field(..., description="Active transaction ID")
    vehicle_type_id: int | None = Field(None, description="Vehicle type override")


class CalculateFeeResponse(BaseModel):
    """Fee recalculation response."""

    fee: int
    vehicle_type_id: int | None = None


# =============================================================================
# Responses
# =============================================================================

class PaymentResponse(BaseModel):
    """Standard payment response."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    message: str
    transaction_id: int | None = None
    fee: int | None = None
    change_amount: int | None = None
    payment_method: str | None = None
    receipt_queued: bool = False


class TransactionLookupResponse(BaseModel):
    """Active transaction lookup response."""

    model_config = ConfigDict(from_attributes=True)

    found: bool
    transaction: dict | None = None
    fee: int | None = None


class EmoneyResultResponse(BaseModel):
    """E-money result processing response."""

    success: bool
    message: str
    transaction_id: int | None = None
    emoney_transaction_id: int | None = None
    status: str | None = None
