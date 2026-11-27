"""`order_events` — the durable, append-only log that is also the bus (04 §3).

`append` only buffers the event on the session; `before_commit` takes `pg_advisory_xact_lock(1)`
and inserts the buffer (always after the row locks a transition already holds, so no lock cycle).
That serialises event commits, so `seq` is commit-ordered: no event with a lower seq can become
visible after a stream has read a higher one, and a cursor `seq > $last` never skips. Because the
lock is taken only at commit, slow work earlier in a transaction (an OSRM call) never holds it.
Streams read this table; nothing else carries an event.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core import clock
from app.models import OrderEvent
from app.services import push

ActorRole = Literal["customer", "restaurant", "rider", "admin", "system"]


@dataclass(frozen=True)
class Actor:
    role: ActorRole
    user_id: uuid.UUID | None = None
    restaurant_id: uuid.UUID | None = None
    rider_id: uuid.UUID | None = None

    @property
    def id(self) -> uuid.UUID | None:
        return self.rider_id or self.user_id


SYSTEM = Actor("system")

STATUS_KINDS = frozenset(
    {
        "placed",
        "accepted",
        "rejected",
        "cancelled",
        "preparing",
        "ready",
        "picked_up",
        "delivered",
        "expired",
    }
)


async def append(
    db: AsyncSession,
    order_id: uuid.UUID,
    kind: str,
    actor: Actor,
    payload: dict[str, Any] | None = None,
    at: dt.datetime | None = None,
) -> OrderEvent:
    ev = OrderEvent(
        order_id=order_id,
        kind=kind,
        actor_role=actor.role,
        actor_id=actor.id,
        payload=payload or {},
        at=at or clock.now(),
    )
    pending(db).append(ev)
    return ev


def pending(db: AsyncSession) -> list[OrderEvent]:
    """Events appended in this transaction, not yet written (demo staging re-stamps them)."""
    return db.info.setdefault(PENDING, [])


PENDING = "pending_order_events"


@event.listens_for(Session, "before_commit")
def _write_pending(session: Session) -> None:
    evs = session.info.pop(PENDING, None)
    if evs:
        session.execute(text("select pg_advisory_xact_lock(1)"))
        push.stage(session, evs)  # who to notify, read now; sent only after the commit lands
        session.add_all(evs)


@event.listens_for(Session, "after_commit")
def _push_after_commit(session: Session) -> None:
    push.committed(session)


@event.listens_for(Session, "after_rollback")
def _push_after_rollback(session: Session) -> None:
    push.dropped(session)


@event.listens_for(Session, "after_transaction_end")
def _drop_pending(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:  # rolled back (or already written)
        session.info.pop(PENDING, None)
