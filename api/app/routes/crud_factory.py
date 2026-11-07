"""Generic CRUD router factory for simple admin-only resources."""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.middleware.auth import require_admin
from api.app.schemas.common import SuccessResponse
from api.app.utils.pagination import PaginationParams, paginated_list
from api.database import get_db

T = TypeVar("T")


def create_crud_router(
    model: type,
    schema_create: type[BaseModel],
    schema_update: type[BaseModel],
    schema_response: type[BaseModel],
    prefix: str,
    tags: list[str],
    search_fields: list[str] | None = None,
    auth_dependency: Callable = require_admin,
    read_auth_dependency: Callable | None = None,
    on_create: Callable[[Any], Awaitable[None]] | None = None,
    on_update: Callable[[Any], Awaitable[None]] | None = None,
    on_delete: Callable[[int], Awaitable[None]] | None = None,
    use_pagination: bool = True,
    not_found_detail: str = "Not found",
) -> APIRouter:
    """Create a standard CRUD router for admin-only resources.

    Args:
        model: SQLAlchemy model class
        schema_create: Pydantic create schema
        schema_update: Pydantic update schema
        schema_response: Pydantic response schema
        prefix: URL prefix (e.g., "/areas")
        tags: OpenAPI tags
        search_fields: Fields to search when pagination.q is provided
        auth_dependency: Auth dependency (default: require_admin)
        read_auth_dependency: Auth for list/get when reads are wider than writes
        on_create: Async hook called after create with the new instance
        on_update: Async hook called after update with the updated instance
        on_delete: Async hook called after delete with the deleted ID
        use_pagination: Whether to use PaginationParams for list endpoint
        not_found_detail: Error message when resource not found
    """
    read_dependency = read_auth_dependency or auth_dependency
    router = APIRouter(prefix=prefix, tags=tags)

    id_path = "/{id}"

    def _apply_search(stmt, q: str | None):
        if q and search_fields:
            conditions = [
                getattr(model, field).ilike(f"%{q}%") for field in search_fields
            ]
            if len(conditions) == 1:
                stmt = stmt.where(conditions[0])
            else:
                from sqlalchemy import or_
                stmt = stmt.where(or_(*conditions))
        return stmt

    if use_pagination:
        @router.get("", response_model=list[schema_response])
        async def list_items(
            pagination: PaginationParams = Depends(),
            db: AsyncSession = Depends(get_db),
            current_user: dict = Depends(read_dependency),
        ) -> list:
            stmt = select(model)
            stmt = _apply_search(stmt, pagination.q)
            result = await paginated_list(db, stmt, skip=pagination.skip, limit=pagination.limit)
            return [schema_response.model_validate(item) for item in result.items]
    else:
        @router.get("", response_model=list[schema_response])
        async def list_items(
            db: AsyncSession = Depends(get_db),
            current_user: dict = Depends(read_dependency),
        ) -> list:
            result = await db.execute(select(model))
            items = result.scalars().all()
            return [schema_response.model_validate(item) for item in items]

    @router.post("", response_model=schema_response, status_code=status.HTTP_201_CREATED)
    async def create_item(
        data: schema_create,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(auth_dependency),
    ):
        item = model(**data.model_dump())
        db.add(item)
        await db.commit()
        await db.refresh(item)
        if on_create:
            await on_create(item)
        return schema_response.model_validate(item)

    @router.get(id_path, response_model=schema_response)
    async def get_item(
        id: int,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(read_dependency),
    ):
        item = await db.get(model, id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
        return schema_response.model_validate(item)

    @router.patch(id_path, response_model=schema_response)
    async def update_item(
        id: int,
        data: schema_update,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(auth_dependency),
    ):
        item = await db.get(model, id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)

        await db.commit()
        await db.refresh(item)
        if on_update:
            await on_update(item)
        return schema_response.model_validate(item)

    @router.delete(id_path, response_model=SuccessResponse)
    async def delete_item(
        id: int,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(auth_dependency),
    ) -> SuccessResponse:
        item = await db.get(model, id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail)
        await db.delete(item)
        await db.commit()
        if on_delete:
            await on_delete(id)
        return SuccessResponse(message=f"{tags[0] if tags else 'Item'} deleted")

    return router
