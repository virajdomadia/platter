"""Own cookie-session auth (04 §9): argon2 passwords, opaque 30-day sessions in `sessions` (the row
id is the SHA-256 of the cookie value, so a leaked table yields no usable cookie), cookie
`pl_session` HttpOnly + SameSite=Lax. Role gates answer 404, never 403, so the board, the rider
app and the admin don't admit they exist to anyone else."""

import asyncio
import datetime as dt
import functools
import hashlib
import secrets
import uuid
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import ApiError, not_found
from app.models import Restaurant, Rider, Role, Session, User

COOKIE = "pl_session"
SESSION_TTL = dt.timedelta(days=30)

_hasher = PasswordHasher()


@functools.cache
def _dummy_hash() -> str:
    return _hasher.hash("platter-no-such-user")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    """Always runs the full argon2 cost, so timing does not reveal which emails exist."""
    try:
        _hasher.verify(stored or _dummy_hash(), password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return bool(stored)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def open_session(db: AsyncSession, user: User) -> tuple[str, dt.datetime]:
    now = clock.now()
    await db.execute(delete(Session).where(Session.expires_at <= now))
    token = secrets.token_urlsafe(32)
    expires = now + SESSION_TTL
    db.add(Session(id=_hash_token(token), user_id=user.id, expires_at=expires, created_at=now))
    await db.commit()
    return token, expires


async def sign_in(db: AsyncSession, email: str, password: str) -> User | None:
    user = (
        await db.execute(select(User).where(User.email == email.strip().lower()))
    ).scalar_one_or_none()
    ok = await asyncio.to_thread(verify_password, user.password_hash if user else None, password)
    return user if ok and user else None


async def close_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.id == _hash_token(token)))
    await db.commit()


def set_cookie(response: Response, token: str, expires: dt.datetime, settings: Settings) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=max(0, int((expires - clock.now()).total_seconds())),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )


def clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE, path="/", httponly=True, samesite="lax", secure=settings.secure_cookies
    )


async def user_for_token(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    row = (
        await db.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.id == _hash_token(token))
        )
    ).first()
    if row is None:
        return None
    session, user = row
    if session.expires_at <= clock.now():
        await db.delete(session)
        await db.commit()
        return None
    return user


# --- dependencies -----------------------------------------------------------------------------


async def current_user(request: Request, db: AsyncSession = Depends(get_session)) -> User | None:
    return await user_for_token(db, request.cookies.get(COOKIE))


async def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise ApiError(401, "unauthorized", "Sign in to continue")
    return user


@dataclass
class RestaurantOwner:
    user: User
    restaurant: Restaurant


@dataclass
class RiderUser:
    user: User
    rider: Rider


async def require_restaurant(
    user: User | None = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> RestaurantOwner:
    if user is None or user.role != Role.restaurant:
        raise not_found()
    restaurant = (
        await db.execute(select(Restaurant).where(Restaurant.owner_user_id == user.id))
    ).scalar_one_or_none()
    if restaurant is None:
        raise not_found()
    return RestaurantOwner(user, restaurant)


async def require_rider(
    user: User | None = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> RiderUser:
    if user is None or user.role != Role.rider:
        raise not_found()
    rider = (await db.execute(select(Rider).where(Rider.user_id == user.id))).scalar_one_or_none()
    if rider is None:
        raise not_found()
    return RiderUser(user, rider)


async def require_admin(user: User | None = Depends(current_user)) -> User:
    if user is None or user.role != Role.admin:
        raise not_found()
    return user


def new_id() -> uuid.UUID:
    return uuid.uuid4()
