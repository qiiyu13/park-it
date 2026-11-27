"""User management routes (admin only)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin, require_operator
from api.app.schemas.common import SuccessResponse
from api.app.schemas.user import UserCreate, UserResponse, UserUpdate
from api.app.services.user import (
    create_user,
    delete_user,
    get_user_by_id,
    list_users,
    update_user,
)
from api.database import get_db

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/workers", response_model=list[UserResponse])
async def list_workers(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_operator),
) -> list[UserResponse]:
    """List active workers (operator/supervisor/admin) for shift handover picker."""
    from sqlalchemy import or_, select

    from api.app.models.user import User

    result = await db.execute(
        select(User)
        .where(User.is_active.is_(True))
        # ponytail: PINs are gone; an old PIN still lists an admin who works
        # shifts. Drop the worker_pin clause once no live site relies on it.
        .where(or_(User.role.in_(("operator", "supervisor")), User.worker_pin.isnot(None)))
        .order_by(User.full_name)
    )
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.get("", response_model=list[UserResponse])
async def get_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> list[UserResponse]:
    """List all users (admin only)."""
    users = await list_users(db, skip=skip, limit=limit)
    return [UserResponse.model_validate(u) for u in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_new_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> UserResponse:
    """Create a new user (admin only)."""
    user = await create_user(db, data)
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> UserResponse:
    """Get user by ID (admin only)."""
    from fastapi import HTTPException

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_existing_user(
    user_id: int,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> UserResponse:
    """Update user (admin only)."""
    from fastapi import HTTPException

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user = await update_user(db, user, data)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", response_model=SuccessResponse)
async def delete_existing_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> SuccessResponse:
    """Delete user (admin only)."""
    from fastapi import HTTPException

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await delete_user(db, user)
    return SuccessResponse(message="User deleted")
