"""Vehicle type routes: operators read (the POS needs them), admins write."""

from api.app.cache.reference_data import (
    invalidate_vehicle_types,
)
from api.app.middleware.auth import require_admin, require_operator
from api.app.models.vehicle_type import VehicleType
from api.app.routes.crud_factory import create_crud_router
from api.app.schemas.vehicle_type import (
    VehicleTypeCreate,
    VehicleTypeResponse,
    VehicleTypeUpdate,
)
from shared.logging import get_logger

logger = get_logger("vehicle_type_routes")


async def _on_create(_item) -> None:
    try:
        await invalidate_vehicle_types()
    except Exception:
        pass


async def _on_update(_item) -> None:
    try:
        await invalidate_vehicle_types()
    except Exception:
        pass


async def _on_delete(_item_id: int) -> None:
    try:
        await invalidate_vehicle_types()
    except Exception:
        pass


router = create_crud_router(
    model=VehicleType,
    schema_create=VehicleTypeCreate,
    schema_update=VehicleTypeUpdate,
    schema_response=VehicleTypeResponse,
    prefix="/vehicle-types",
    tags=["Vehicle Types"],
    search_fields=["name", "code"],
    auth_dependency=require_admin,
    read_auth_dependency=require_operator,
    on_create=_on_create,
    on_update=_on_update,
    on_delete=_on_delete,
    not_found_detail="Vehicle type not found",
)
