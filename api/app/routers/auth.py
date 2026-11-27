"""`/auth/*` (06 §C): sign up / in / out, me, and the four one-tap demo logins."""

import asyncio

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.core.config import Settings, current_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.models import Restaurant, Rider, Role, User
from app.services import auth, demo, dispatch, limits

router = APIRouter(prefix="/auth", tags=["auth"])

DEMO_EMAILS = {
    "customer": demo.DEMO_CUSTOMER_EMAIL,
    "restaurant": f"owner.{demo.DEMO_RESTAURANT_SLUG}@platter.demo",
    "rider": demo.DEMO_RIDER_EMAIL,
    "admin": "admin@platter.demo",
}


async def me_of(db: AsyncSession, user: User) -> s.Me:
    me = s.Me(id=str(user.id), name=user.name, email=user.email, role=user.role.value)  # type: ignore[arg-type]
    if user.role == Role.restaurant:
        r = (
            await db.execute(select(Restaurant).where(Restaurant.owner_user_id == user.id))
        ).scalar_one_or_none()
        if r:
            me.restaurant = s.MeRestaurant(id=str(r.id), slug=r.slug, name=r.name)
    if user.role == Role.rider:
        rider = (
            await db.execute(select(Rider).where(Rider.user_id == user.id))
        ).scalar_one_or_none()
        if rider:
            me.rider = s.MeRider(id=str(rider.id), name=rider.name, status=rider.status.value)
    return me


async def _signed_in(db: AsyncSession, user: User, response: Response, settings: Settings) -> s.Me:
    token, expires = await auth.open_session(db, user)
    auth.set_cookie(response, token, expires, settings)
    return await me_of(db, user)


@router.post("/sign-up", response_model=s.Me, status_code=201)
async def sign_up(
    body: s.SignUp,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.Me:
    await limits.hit(db, f"sign-up:{limits.client_ip(request, settings)}", 10)
    if body.email.lower().endswith("platter.demo"):  # the seeded demo and sim accounts' domain
        raise ApiError(422, "validation", "Use your own email address", {"fields": {"email": ""}})
    password_hash = await asyncio.to_thread(auth.hash_password, body.password)
    user = User(
        id=auth.new_id(),
        email=body.email.lower(),
        password_hash=password_hash,
        name=body.name.strip(),
        phone=(body.phone or "").strip() or None,
        role=Role.customer,
        created_at=clock.now(),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ApiError(409, "email_taken", "An account with this email already exists") from exc
    return await _signed_in(db, user, response, settings)


@router.post("/sign-in", response_model=s.Me)
async def sign_in(
    body: s.SignIn,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.Me:
    await limits.hit(db, f"sign-in:{body.email.strip().lower()}", 10)
    user = await auth.sign_in(db, body.email, body.password)
    if user is None:
        raise ApiError(401, "bad_credentials", "That email and password don't match")
    return await _signed_in(db, user, response, settings)


@router.post("/sign-out", status_code=204)
async def sign_out(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> Response:
    token = request.cookies.get(auth.COOKIE)
    if token:
        user = await auth.user_for_token(db, token)
        if user is not None:
            await dispatch.forget_rider(db, user.id)  # a real phone's fix goes with it
        await auth.close_session(db, token)
    auth.clear_cookie(response, settings)
    response.status_code = 204
    return response


@router.get("/me", response_model=s.Me)
async def me(
    user: User = Depends(auth.require_user), db: AsyncSession = Depends(get_session)
) -> s.Me:
    return await me_of(db, user)


@router.post("/demo", response_model=s.Me)
async def demo_login(
    body: s.DemoIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> s.Me:
    """Sign in as one of the four seeded demo accounts — and make sure there is something to see:
    an order on the way, tickets on the board, a job on the rider's phone, orders on the map."""
    await limits.hit(db, f"demo:{limits.client_ip(request, settings)}", 30)
    await dispatch.prune(db)
    role = body.as_
    user = (
        await db.execute(select(User).where(User.email == DEMO_EMAILS[role]))
    ).scalar_one_or_none()
    if user is None:
        raise ApiError(503, "not_seeded", "The demo data isn't loaded yet")
    if role == "customer":
        await demo.ensure_customer_scene(db, user)
    elif role == "restaurant":
        r = (
            await db.execute(select(Restaurant).where(Restaurant.owner_user_id == user.id))
        ).scalar_one()
        await demo.ensure_restaurant_scene(db, r)
    elif role == "rider":
        rider = (await db.execute(select(Rider).where(Rider.user_id == user.id))).scalar_one()
        await demo.ensure_rider_scene(db, rider)
    else:
        await demo.ensure_admin_scene(db)
    await db.commit()
    return await _signed_in(db, user, response, settings)
