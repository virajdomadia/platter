"""ORM models for 06 §A (v1). The schema itself is created by Alembic `0001_v1` in raw SQL — these
mappings mirror it. Every geography column is `geography(Point, 4326)`; the API only ever hands
out `{ lat, lng }` (see `app.models.geo`)."""

import datetime as dt
import enum
import uuid
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Role(enum.StrEnum):
    customer = "customer"
    restaurant = "restaurant"
    rider = "rider"
    admin = "admin"


class RiderStatus(enum.StrEnum):
    offline = "offline"
    available = "available"
    busy = "busy"


class OrderStatus(enum.StrEnum):
    pending_payment = "pending_payment"
    placed = "placed"
    accepted = "accepted"
    preparing = "preparing"
    ready = "ready"
    picked_up = "picked_up"
    delivered = "delivered"
    rejected = "rejected"
    cancelled = "cancelled"
    expired = "expired"


ACTIVE_STATUSES = (
    OrderStatus.placed,
    OrderStatus.accepted,
    OrderStatus.preparing,
    OrderStatus.ready,
    OrderStatus.picked_up,
)
CLOSED_STATUSES = (
    OrderStatus.delivered,
    OrderStatus.rejected,
    OrderStatus.cancelled,
    OrderStatus.expired,
)


class PaymentKind(enum.StrEnum):
    cod = "cod"
    razorpay = "razorpay"


class LegKind(enum.StrEnum):
    to_restaurant = "to_restaurant"
    to_customer = "to_customer"


class RouteMethod(enum.StrEnum):
    osrm = "osrm"
    line = "line"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    return Enum(e, name=name, create_type=False, values_callable=lambda x: [m.value for m in x])


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ts(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


POINT = Geography(geometry_type="POINT", srid=4326, spatial_index=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid()
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), default=Role.customer)
    # Seeded demo/sim account (0002). Operator screens are public demos: they only see demo orders.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = _ts(False)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # sha256 of the cookie value
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[dt.datetime] = _ts(False)
    created_at: Mapped[dt.datetime] = _ts(False)


class Address(Base):
    __tablename__ = "addresses"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(Text)
    line: Mapped[str] = mapped_column(Text)
    loc: Mapped[Any] = mapped_column(POINT)
    created_at: Mapped[dt.datetime] = _ts(False)


class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[uuid.UUID] = _uuid()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    slug: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str] = mapped_column(Text)
    area: Mapped[str] = mapped_column(Text)
    cuisines: Mapped[list[str]] = mapped_column(ARRAY(Text))
    is_veg: Mapped[bool] = mapped_column(Boolean, default=False)
    loc: Mapped[Any] = mapped_column(POINT)
    address: Mapped[str] = mapped_column(Text)
    prep_min: Mapped[int] = mapped_column(Integer, default=15)
    hours: Mapped[dict[str, list[list[str]]]] = mapped_column(JSONB)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    cover_url: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[float | None] = mapped_column(Numeric(2, 1))
    # v1 addition: when the board last had a live stream open. The kitchen autopilot
    # (services/sim.py) only runs a restaurant's tickets while nobody is on its board.
    board_seen_at: Mapped[dt.datetime | None] = _ts()
    # v2: the demo kitchen's private menu-editor copy (services/menu.py): never public.
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)
    # v2: real customers' ratings only (a demo visitor's never moves the public score).
    rating_sum: Mapped[int] = mapped_column(Integer, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = _ts(False)


class MenuCategory(Base):
    __tablename__ = "menu_categories"
    id: Mapped[uuid.UUID] = _uuid()
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer)


class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[uuid.UUID] = _uuid()
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("menu_categories.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    price_paise: Mapped[int] = mapped_column(Integer)
    is_veg: Mapped[bool] = mapped_column(Boolean)
    photo_url: Mapped[str | None] = mapped_column(Text)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer)


class Rider(Base):
    __tablename__ = "riders"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text)
    vehicle: Mapped[str] = mapped_column(Text)
    is_sim: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[RiderStatus] = mapped_column(
        _enum(RiderStatus, "rider_status"), default=RiderStatus.available
    )
    speed_kmh: Mapped[float] = mapped_column(Numeric(4, 1), default=22.0)
    created_at: Mapped[dt.datetime] = _ts(False)


class RiderPosition(Base):
    __tablename__ = "rider_positions"
    rider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("riders.id", ondelete="CASCADE"), primary_key=True
    )
    loc: Mapped[Any] = mapped_column(POINT)
    heading: Mapped[int | None] = mapped_column(SmallInteger)
    speed_mps: Mapped[float | None] = mapped_column(Numeric(5, 2))
    recorded_at: Mapped[dt.datetime] = _ts(False)
    client_at: Mapped[dt.datetime | None] = _ts()


class RiderTrack(Base):
    __tablename__ = "rider_track"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("riders.id", ondelete="CASCADE"))
    at: Mapped[dt.datetime] = _ts(False)
    loc: Mapped[Any] = mapped_column(POINT)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = _uuid()
    number: Mapped[str] = mapped_column(Text, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    restaurant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurants.id"))
    rider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("riders.id"))
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus, "order_status"))
    payment: Mapped[PaymentKind] = mapped_column(_enum(PaymentKind, "payment_kind"))
    address_line: Mapped[str] = mapped_column(Text)
    drop_loc: Mapped[Any] = mapped_column(POINT)
    subtotal_paise: Mapped[int] = mapped_column(Integer)
    delivery_fee_paise: Mapped[int] = mapped_column(Integer)
    platform_fee_paise: Mapped[int] = mapped_column(Integer)
    total_paise: Mapped[int] = mapped_column(Integer)
    distance_m: Mapped[int] = mapped_column(Integer)
    route_method: Mapped[RouteMethod] = mapped_column(_enum(RouteMethod, "route_method"))
    eta_s: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    razorpay_order_id: Mapped[str | None] = mapped_column(Text, unique=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)  # the customer's is_demo
    created_at: Mapped[dt.datetime] = _ts(False)
    placed_at: Mapped[dt.datetime | None] = _ts()
    accepted_at: Mapped[dt.datetime | None] = _ts()
    preparing_at: Mapped[dt.datetime | None] = _ts()
    ready_at: Mapped[dt.datetime | None] = _ts()
    picked_up_at: Mapped[dt.datetime | None] = _ts()
    delivered_at: Mapped[dt.datetime | None] = _ts()
    rejected_at: Mapped[dt.datetime | None] = _ts()
    cancelled_at: Mapped[dt.datetime | None] = _ts()
    expired_at: Mapped[dt.datetime | None] = _ts()


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[uuid.UUID] = _uuid()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("menu_items.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(Text)
    price_paise: Mapped[int] = mapped_column(Integer)
    qty: Mapped[int] = mapped_column(Integer)
    is_veg: Mapped[bool] = mapped_column(Boolean)


class OrderEvent(Base):
    __tablename__ = "order_events"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    actor_role: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    at: Mapped[dt.datetime] = _ts(False)


class RiderLeg(Base):
    __tablename__ = "rider_legs"
    id: Mapped[uuid.UUID] = _uuid()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("riders.id", ondelete="CASCADE"))
    kind: Mapped[LegKind] = mapped_column(_enum(LegKind, "leg_kind"))
    polyline: Mapped[str] = mapped_column(Text)
    distance_m: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[int] = mapped_column(Integer)
    method: Mapped[RouteMethod] = mapped_column(_enum(RouteMethod, "route_method"))
    started_at: Mapped[dt.datetime] = _ts(False)
    arrived_at: Mapped[dt.datetime | None] = _ts()
    ended_at: Mapped[dt.datetime | None] = _ts()


class Offer(Base):
    """v2: one rider's 30 s to take an order (`state` sent → accepted | declined | expired)."""

    __tablename__ = "offers"
    id: Mapped[uuid.UUID] = _uuid()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("riders.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(Text, default="sent")
    expires_at: Mapped[dt.datetime] = _ts(False)
    created_at: Mapped[dt.datetime] = _ts(False)
    closed_at: Mapped[dt.datetime | None] = _ts()


class PushSubscription(Base):
    """v2: one browser's Web Push endpoint, tied to the session that subscribed it."""

    __tablename__ = "push_subscriptions"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _ts(False)


class Rating(Base):
    __tablename__ = "ratings"
    id: Mapped[uuid.UUID] = _uuid()
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    restaurant_stars: Mapped[int] = mapped_column(SmallInteger)
    rider_stars: Mapped[int | None] = mapped_column(SmallInteger)
    line: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[dt.datetime] = _ts(False)


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[uuid.UUID] = _uuid()
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    amount_paise: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    razorpay_refund_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _ts(False)
    updated_at: Mapped[dt.datetime] = _ts(False)


class Payout(Base):
    __tablename__ = "payouts"
    id: Mapped[uuid.UUID] = _uuid()
    account: Mapped[str] = mapped_column(Text)
    amount_paise: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str] = mapped_column(Text)
    paid_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean)
    paid_at: Mapped[dt.datetime] = _ts(False)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    amount_paise: Mapped[int] = mapped_column(Integer)  # signed
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    payout_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payouts.id", ondelete="CASCADE")
    )
    is_demo: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[dt.datetime] = _ts(False)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    event: Mapped[str] = mapped_column(Text)
    received_at: Mapped[dt.datetime] = _ts(False)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[dt.datetime] = _ts(False)
    hits: Mapped[int] = mapped_column(Integer)
