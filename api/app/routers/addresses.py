"""Saved addresses (S11): label, line, pin."""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.core.db import get_session
from app.core.errors import ApiError, not_found
from app.models import Address, User
from app.models.geo import latlng, make_point
from app.services import auth

router = APIRouter(prefix="/addresses", tags=["addresses"])
MAX_ADDRESSES = 12


def out(a: Address) -> s.AddressOut:
    lat, lng = latlng(a.loc)
    return s.AddressOut(id=str(a.id), label=a.label, line=a.line, lat=lat, lng=lng)


@router.get("", response_model=list[s.AddressOut])
async def list_addresses(
    user: User = Depends(auth.require_user), db: AsyncSession = Depends(get_session)
) -> list[s.AddressOut]:
    rows = (
        await db.execute(
            select(Address).where(Address.user_id == user.id).order_by(Address.created_at)
        )
    ).scalars()
    return [out(a) for a in rows]


@router.post("", response_model=s.AddressOut, status_code=201)
async def add_address(
    body: s.AddressIn,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
) -> s.AddressOut:
    count = (
        await db.execute(text("select count(*) from addresses where user_id = :u"), {"u": user.id})
    ).scalar_one()
    if count >= MAX_ADDRESSES:
        raise ApiError(422, "too_many", f"You can keep up to {MAX_ADDRESSES} addresses")
    a = Address(
        id=uuid.uuid4(),
        user_id=user.id,
        label=body.label.strip(),
        line=body.line.strip(),
        loc=make_point(body.lat, body.lng),
        created_at=clock.now(),
    )
    db.add(a)
    await db.commit()
    return s.AddressOut(id=str(a.id), label=a.label, line=a.line, lat=body.lat, lng=body.lng)


@router.delete("/{address_id}", status_code=204)
async def delete_address(
    address_id: uuid.UUID,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    a = await db.get(Address, address_id)
    if a is None or a.user_id != user.id:
        raise not_found("No such address")
    await db.delete(a)
    await db.commit()
    return Response(status_code=204)
