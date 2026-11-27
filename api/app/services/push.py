"""Web Push (v2 L2): a notification when the tab is closed, derived from the event log.

* **Who hears what** — customer: accepted / picked_up / delivered / rejected; restaurant owner:
  placed; rider: offer_sent / rider_assigned / rider_reassigned. Fixed templates only: no free
  text a visitor typed (a reject reason, a note) ever reaches someone else's lock screen.
* **The wall** — a message goes only to a user on the order's own side of the demo partition
  (`users.is_demo = orders.is_demo`): a demo visitor's tap can never notify a real person, and a
  real order never notifies the public demo board or phone.
* **After commit, never in the way** — `stage()` runs inside the commit hook (`events.py`) and
  only reads; `after_commit` marks the batch ready; `drain()` sends it once the order action is
  committed. Every failure is logged and swallowed: push can't fail or roll back an order action.
* **Subscriptions belong to a browser session** (`push_subscriptions.session_id`): signing out or
  the session expiring (a day for demo logins) drops it, so a shared demo account doesn't keep
  ringing yesterday's visitor. A dead endpoint (404 / 410) is deleted.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.models import OrderEvent, PushSubscription

log = logging.getLogger(__name__)

STAGED, READY = "push_staged", "push_ready"
SEND_TIMEOUT_S = 4.0
MAX_PER_USER = 10  # a shared demo account collects visitors' browsers: ring only the newest few
MAX_BATCH = 50
# Endpoints are URLs we POST to: only the browsers' push services, never an arbitrary host (SSRF).
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)

CUSTOMER = {"accepted", "picked_up", "delivered", "rejected"}
RIDER = {"offer_sent", "rider_assigned", "rider_reassigned"}


@dataclass(frozen=True)
class Message:
    endpoint: str
    p256dh: str
    auth: str
    payload: str
    ttl: int


def allowed_endpoint(endpoint: str) -> bool:
    try:
        u = urlsplit(endpoint)
        host = (u.hostname or "").lower()
        port = u.port  # raises on a malformed port
    except ValueError:
        return False
    return (
        u.scheme == "https"
        and port is None
        and not u.username
        and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)
    )


def _text(kind: str, number: str, restaurant: str, items: int) -> tuple[str, str, str]:
    """(title, body, path) — fixed templates over seeded names and numbers only."""
    return {
        "accepted": (f"{restaurant} accepted your order", f"{number} is being prepared.", "o"),
        "picked_up": ("Your order is on the way", f"{number} left {restaurant}.", "o"),
        "delivered": ("Delivered", f"{number} from {restaurant}. Enjoy your meal.", "o"),
        "rejected": (f"{restaurant} couldn't take your order", f"Open {number} for details.", "o"),
        "placed": (f"New order {number}", f"{items} item{'s' if items != 1 else ''}.", "r"),
        "offer_sent": ("New job offer", f"{restaurant}: 30 seconds to accept.", "d"),
        "rider_assigned": ("New job", f"Pick up {number} at {restaurant}.", "d"),
        "rider_reassigned": ("New job", f"Pick up {number} at {restaurant}.", "d"),
    }[kind]


def stage(session: Session, evs: list[OrderEvent]) -> None:
    """Inside the commit (sync, before the events are flushed): resolve recipients and their
    live subscriptions. Read-only; any error here is logged and push is skipped."""
    wanted = [e for e in evs if e.kind in CUSTOMER or e.kind == "placed" or e.kind in RIDER]
    if not wanted:
        return
    try:
        # A savepoint: a failed lookup aborts only itself, never the order's own transaction.
        with session.begin_nested():
            found = [m for ev in wanted for m in _messages(session, ev)]
        session.info.setdefault(STAGED, []).extend(found)
    except Exception:  # noqa: BLE001 - push must never break the commit it rides on
        log.exception("push: staging failed")


def _messages(session: Session, ev: OrderEvent) -> list[Message]:
    if ev.kind in CUSTOMER:
        who = "o.user_id"
    elif ev.kind == "placed":
        who = "r.owner_user_id"
    else:
        who = "(select user_id from riders where id = cast(:rider as uuid))"
    rows = session.execute(
        text(
            f"""
            select o.id, o.number, r.name,
                   (select coalesce(sum(qty), 0) from order_items where order_id = o.id),
                   s.endpoint, s.p256dh, s.auth
            from orders o
            join restaurants r on r.id = o.restaurant_id
            join users u on u.id = {who}
            join lateral (
              select s.* from push_subscriptions s
              join sessions x on x.id = s.session_id and x.expires_at > :now
              where s.user_id = u.id order by s.created_at desc limit :cap
            ) s on true
            where o.id = :order and u.is_demo = o.is_demo
            """  # noqa: S608 - `who` is one of three fixed expressions above
        ),
        {
            "order": ev.order_id,
            "rider": ev.payload.get("rider_id"),
            "now": clock.now(),
            "cap": MAX_PER_USER,
        },
    ).all()
    out = []
    for oid, number, restaurant, items, endpoint, p256dh, auth in rows:
        title, body, where = _text(ev.kind, number, restaurant, int(items))
        url = {"o": f"/orders/{oid}", "r": "/restaurant", "d": "/rider"}[where]
        payload = json.dumps({"title": title, "body": body, "url": url, "tag": f"{oid}:{ev.kind}"})
        ttl = 30 if ev.kind == "offer_sent" else 3600  # a stale offer is worse than none
        out.append(Message(endpoint, p256dh, auth, payload, ttl))
    return out


def committed(session: Session) -> None:
    staged = session.info.pop(STAGED, None)
    if staged:
        session.info.setdefault(READY, []).extend(staged)


def dropped(session: Session) -> None:
    session.info.pop(STAGED, None)


async def deliver(m: Message) -> int:
    """Send one message; returns the push service's HTTP status (0 = didn't get one)."""
    from pywebpush import WebPushException, webpush_async

    settings = get_settings()
    assert settings.vapid_private_key is not None  # noqa: S101 - checked by drain()
    try:
        res = await webpush_async(
            {"endpoint": m.endpoint, "keys": {"p256dh": m.p256dh, "auth": m.auth}},
            data=m.payload,
            vapid_private_key=settings.vapid_private_key.get_secret_value(),
            vapid_claims={"sub": settings.vapid_subject},
            ttl=m.ttl,
            timeout=SEND_TIMEOUT_S,
        )
        return int(getattr(res, "status", 201))
    except WebPushException as exc:
        return int(getattr(exc.response, "status", 0) or 0)


async def drain(db: AsyncSession) -> None:
    """Send what this session committed. Called after the order action's commit (the request's
    teardown, each stream tick). Never raises."""
    ready: list[Message] = (db.sync_session.info.pop(READY, None) or [])[:MAX_BATCH]
    if not ready or not get_settings().push_enabled:
        return
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(deliver(m) for m in ready), return_exceptions=True),
            SEND_TIMEOUT_S + 1,
        )
        dead = [m.endpoint for m, r in zip(ready, results, strict=True) if r in (404, 410)]
        for r in results:
            if isinstance(r, BaseException):
                log.warning("push: send failed: %s", type(r).__name__)
        if dead:
            await db.execute(delete(PushSubscription).where(PushSubscription.endpoint.in_(dead)))
            await db.commit()
    except Exception:  # noqa: BLE001 - a push problem is logged, never raised into an order action
        log.exception("push: drain failed")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001 - e.g. the connection is already gone
            log.warning("push: rollback after a failed drain also failed")
