"""Web Push opt-in (v2 L2, 06 §C): the VAPID public key and this browser's subscription."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core import clock
from app.core.config import Settings, current_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.models import PushSubscription, User
from app.services import auth, limits
from app.services import push as push_service

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/key", response_model=s.PushKeyOut)
async def key(settings: Settings = Depends(current_settings)) -> s.PushKeyOut:
    return s.PushKeyOut(key=settings.vapid_public_key if settings.push_enabled else None)


@router.post("/subscribe", status_code=204)
async def subscribe(
    body: s.PushSubscribeIn,
    request: Request,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(current_settings),
) -> Response:
    """Ties this browser's endpoint to the signed-in session. The same browser subscribing again
    (or as someone else) moves the endpoint: it only rings for whoever is signed in there."""
    await limits.hit(db, f"push:{limits.client_ip(request, settings)}", 20)
    if not push_service.allowed_endpoint(body.endpoint):
        raise ApiError(422, "validation", "That isn't a browser push service address")
    session_id = auth.hash_token(request.cookies.get(auth.COOKIE, ""))
    await db.execute(
        text(
            "insert into push_subscriptions (id, user_id, session_id, endpoint, p256dh, auth,"
            " created_at) values (gen_random_uuid(), :u, :s, :e, :p, :a, :now)"
            " on conflict (endpoint) do update set user_id = excluded.user_id,"
            " session_id = excluded.session_id, p256dh = excluded.p256dh, auth = excluded.auth,"
            " created_at = excluded.created_at"
        ),
        {
            "u": user.id,
            "s": session_id,
            "e": body.endpoint,
            "p": body.keys.p256dh,
            "a": body.keys.auth,
            "now": clock.now(),
        },
    )
    await db.commit()
    return Response(status_code=204)


@router.delete("/subscribe", status_code=204)
async def unsubscribe(
    body: s.PushUnsubscribeIn,
    user: User = Depends(auth.require_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id
        )
    )
    await db.commit()
    return Response(status_code=204)
