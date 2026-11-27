"""Request / response models — the OpenAPI contract (06 §C, §D). Money is integer paise,
distances integer metres, times seconds; points are `{ lat, lng }`."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints

OrderStatusT = Literal[
    "pending_payment",
    "placed",
    "accepted",
    "preparing",
    "ready",
    "picked_up",
    "delivered",
    "rejected",
    "cancelled",
    "expired",
]
RoleT = Literal["customer", "restaurant", "rider", "admin"]


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


# --- auth -------------------------------------------------------------------------------------


class SignUp(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=20)


class SignIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class DemoIn(BaseModel):
    as_: RoleT = Field(alias="as")


class MeRestaurant(BaseModel):
    id: str
    slug: str
    name: str


class MeRider(BaseModel):
    id: str
    name: str
    status: str


class Me(BaseModel):
    id: str
    name: str
    email: str
    role: RoleT
    restaurant: MeRestaurant | None = None
    rider: MeRider | None = None


# --- discovery --------------------------------------------------------------------------------


class Photo(BaseModel):
    url: str
    width: int
    height: int


class RestaurantCard(BaseModel):
    id: str
    slug: str
    name: str
    area: str
    cuisines: list[str]
    is_veg: bool
    cover: Photo | None
    rating: float | None
    prep_min: int
    lat: float
    lng: float
    distance_m: int
    eta_s: int
    delivery_fee_paise: int
    orderable: bool
    reason: Literal["too_far", "closed"] | None = None
    hours_label: str
    opens: str | None = None


class MenuItemOut(BaseModel):
    id: str
    name: str
    description: str | None
    price_paise: int
    is_veg: bool
    photo: Photo | None
    is_available: bool


class CategoryOut(BaseModel):
    id: str
    name: str
    items: list[MenuItemOut]


class RestaurantOut(RestaurantCard):
    address: str
    hours: dict[str, list[list[str]]]
    categories: list[CategoryOut]


class Place(BaseModel):
    label: str
    line: str
    lat: float
    lng: float


# --- addresses --------------------------------------------------------------------------------


class AddressIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    line: str = Field(min_length=3, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class AddressOut(AddressIn):
    id: str


# --- orders -----------------------------------------------------------------------------------


class CartLine(BaseModel):
    id: str
    qty: int = Field(ge=1, le=20)


class QuoteIn(BaseModel):
    restaurant_id: str
    items: list[CartLine] = Field(min_length=1, max_length=40)
    address: Point


class OrderIn(QuoteIn):
    address_line: str = Field(min_length=3, max_length=200)
    payment: Literal["cod", "razorpay"] = "cod"
    note: str | None = Field(default=None, max_length=280)
    # The total the checkout showed; a different server total is a 409 `price_changed`.
    expected_total_paise: int | None = Field(default=None, ge=0)


class QuoteItem(BaseModel):
    id: str
    name: str
    price_paise: int
    qty: int
    is_veg: bool


class QuoteOut(BaseModel):
    items: list[QuoteItem]
    subtotal_paise: int
    delivery_fee_paise: int
    platform_fee_paise: int
    total_paise: int
    distance_m: int
    eta_s: int
    method: Literal["osrm", "line"]


class OrderRestaurant(BaseModel):
    id: str
    slug: str
    name: str
    area: str
    address: str
    lat: float
    lng: float
    cover: Photo | None


class Drop(BaseModel):
    line: str
    lat: float
    lng: float


class OrderItemOut(BaseModel):
    name: str
    price_paise: int
    qty: int
    is_veg: bool


class Totals(BaseModel):
    subtotal_paise: int
    delivery_fee_paise: int
    platform_fee_paise: int
    total_paise: int
    distance_m: int


class RiderPublic(BaseModel):
    id: str
    name: str
    vehicle: str
    phone_masked: str


class RouteOut(BaseModel):
    order_id: str
    leg_id: str
    kind: Literal["to_restaurant", "to_customer"]
    polyline: str
    distance_m: int
    duration_s: int
    method: Literal["osrm", "line"]
    started_at: dt.datetime


class EtaOut(BaseModel):
    order_id: str
    eta_s: int
    method: Literal["osrm", "line"]
    phase: Literal["cooking", "to_restaurant", "to_customer"]


class StatusEventOut(BaseModel):
    order_id: str
    status: OrderStatusT
    at: dt.datetime
    reason: str | None = None


class RiderFix(BaseModel):
    order_id: str | None = None
    rider_id: str
    lat: float
    lng: float
    heading: int | None
    speed_mps: float | None
    at: dt.datetime
    distance_m: int | None = None


class OrderOut(BaseModel):
    id: str
    number: str
    status: OrderStatusT
    payment: Literal["cod", "razorpay"]
    restaurant: OrderRestaurant
    drop: Drop
    items: list[OrderItemOut]
    totals: Totals
    note: str | None
    reject_reason: str | None
    rider: RiderPublic | None
    rider_position: RiderFix | None
    legs: list[RouteOut]
    trail: list[list[float]]
    eta: EtaOut | None
    events: list[StatusEventOut]
    timestamps: dict[str, dt.datetime]
    created_at: dt.datetime
    seq: int
    offer_attempts: int = 0  # riders asked so far ("Finding a rider", v2)


class RazorpayStart(BaseModel):
    order_id: str
    key_id: str
    amount_paise: int
    name: str
    description: str
    prefill: dict[str, str]


class OrderStart(BaseModel):
    order: OrderOut
    razorpay: RazorpayStart | None = None


class VerifyIn(BaseModel):
    razorpay_payment_id: str = Field(min_length=1, max_length=100)
    razorpay_signature: str = Field(min_length=1, max_length=200)


class OrderCard(BaseModel):
    id: str
    number: str
    status: OrderStatusT
    restaurant_name: str
    restaurant_slug: str
    cover: Photo | None
    items_summary: str
    total_paise: int
    created_at: dt.datetime


class PaymentsConfig(BaseModel):
    razorpay_key_id: str | None


# --- restaurant board -------------------------------------------------------------------------


class TicketItem(BaseModel):
    name: str
    qty: int
    is_veg: bool


class TicketRider(BaseModel):
    name: str
    distance_m: int | None
    eta_s: int | None
    phase: Literal["to_restaurant", "waiting", "to_customer"]


class Ticket(BaseModel):
    id: str
    number: str
    status: OrderStatusT
    placed_at: dt.datetime
    age_s: int
    customer_first_name: str
    payment: Literal["cod", "razorpay"]
    note: str | None
    items: list[TicketItem]
    total_paise: int
    rider: TicketRider | None


class BoardToday(BaseModel):
    orders: int
    revenue_paise: int
    avg_accept_s: int | None


class BoardRestaurant(BaseModel):
    id: str
    slug: str
    name: str
    area: str
    is_open: bool
    hours_label: str


class Board(BaseModel):
    restaurant: BoardRestaurant
    new: list[Ticket]
    cooking: list[Ticket]
    ready: list[Ticket]
    out: list[Ticket]
    today: BoardToday
    seq: int


class RestaurantTransitionIn(BaseModel):
    to: Literal["accepted", "rejected", "preparing", "ready"]
    reason: str | None = Field(default=None, max_length=200)


# Stripped before the length check, so "   " is refused rather than saved as an empty name.
Name80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Name60 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Text280 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=280)]


class AvailabilityIn(BaseModel):
    """PATCH /restaurant/items/{id}: any subset (v1 sent only `is_available`)."""

    is_available: bool | None = None
    name: Name80 | None = None
    description: Text280 | None = None
    price_paise: int | None = Field(default=None, ge=100, le=1_000_000)
    is_veg: bool | None = None
    photo_url: str | None = Field(default=None, max_length=300)
    category_id: str | None = None


class ItemIn(BaseModel):
    category_id: str
    name: Name80
    description: Text280 | None = None
    price_paise: int = Field(ge=100, le=1_000_000)  # ₹1 to ₹10,000
    is_veg: bool
    photo_url: str | None = Field(default=None, max_length=300)
    is_available: bool = True


class CategoryIn(BaseModel):
    name: Name60


class CategoryOrderIn(BaseModel):
    ids: list[str] = Field(max_length=50)


class DetailsIn(BaseModel):
    hours: dict[str, list[list[str]]] | None = None
    is_open: bool | None = None
    prep_min: int | None = Field(default=None, ge=5, le=90)
    cover_url: str | None = Field(default=None, max_length=300)


class RestaurantDetails(BaseModel):
    hours: dict[str, list[list[str]]]
    is_open: bool  # the owner's switch; `restaurant.is_open` also applies the hours
    prep_min: int
    cover: Photo | None


class MenuItemAdmin(MenuItemOut):
    category_id: str


class MenuOut(BaseModel):
    restaurant: BoardRestaurant
    categories: list[CategoryOut]
    details: RestaurantDetails | None = None
    sandbox: bool = False  # the public demo login edits a private copy (v2)


# --- rider ------------------------------------------------------------------------------------


class PositionIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    heading: float | None = Field(default=None, ge=0, le=360)
    speed_mps: float | None = Field(default=None, ge=0, le=80)
    accuracy_m: float | None = Field(default=None, ge=0)
    at: dt.datetime


class RiderTransitionIn(BaseModel):
    to: Literal["picked_up", "delivered"]


class JobPlace(BaseModel):
    name: str
    line: str
    lat: float
    lng: float


class Job(BaseModel):
    order_id: str
    number: str
    status: OrderStatusT
    phase: Literal["to_restaurant", "waiting", "to_customer"]
    restaurant: JobPlace
    drop: JobPlace
    customer_first_name: str
    items: list[TicketItem]
    items_count: int
    payment: Literal["cod", "razorpay"]
    total_paise: int
    note: str | None
    leg: RouteOut | None
    pay_preview_paise: int


class RiderSelf(BaseModel):
    id: str
    name: str
    vehicle: str
    status: str


class RiderToday(BaseModel):
    deliveries: int
    pay_paise: int


class RiderOffer(BaseModel):
    id: str
    expires_at: dt.datetime
    expires_in_s: int
    job: Job


class RiderMe(BaseModel):
    rider: RiderSelf
    job: Job | None
    today: RiderToday
    last_fix_s: int | None
    seq: int
    offer: RiderOffer | None = None


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=12, max_length=1000)
    keys: PushKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=12, max_length=1000)


class PushKeyOut(BaseModel):
    key: str | None  # None = push is switched off on this deployment


class RiderStatusIn(BaseModel):
    status: Literal["available", "offline"]


# --- admin ------------------------------------------------------------------------------------


class AdminRider(BaseModel):
    id: str
    name: str
    status: Literal["offline", "available", "busy"]
    is_sim: bool
    vehicle: str
    lat: float | None
    lng: float | None
    heading: int | None
    current_order: str | None
    last_fix_s: int | None
    distance_m: int | None = None


class AdminOrder(BaseModel):
    id: str
    number: str
    status: OrderStatusT
    restaurant_name: str
    restaurant: Point
    drop: Point
    rider_id: str | None
    rider_name: str | None
    age_s: int
    status_age_s: int
    stuck: Literal["unaccepted", "no_rider", "not_picked_up", "kitchen_late"] | None
    legs: list[RouteOut]
    total_paise: int
    offer_attempts: int = 0


class AdminToday(BaseModel):
    orders: int
    delivered: int
    revenue_paise: int
    avg_delivery_s: int | None


class AdminMap(BaseModel):
    orders: list[AdminOrder]
    riders: list[AdminRider]
    restaurants: list[RestaurantCard]
    today: AdminToday
    seq: int


class ReassignIn(BaseModel):
    rider_id: str
