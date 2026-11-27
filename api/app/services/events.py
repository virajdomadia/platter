"""`order_events` — the durable, append-only log that is also the bus (04 §3).

Every insert first takes `pg_advisory_xact_lock(1)` (always after the row locks a transition
already holds, so no lock cycle). That serialises event commits, so `seq` is commit-ordered: no
event with a lower seq can become visible after a stream has read a higher one, and a cursor
`seq > $last` never skips. Streams read this table; nothing else carries an event.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models import OrderEvent

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
    await db.execute(text("select pg_advisory_xact_lock(1)"))
    event = OrderEvent(
        order_id=order_id,
        kind=kind,
        actor_role=actor.role,
        actor_id=actor.id,
        payload=payload or {},
        at=at or clock.now(),
    )
    db.add(event)
    await db.flush()
    return event
