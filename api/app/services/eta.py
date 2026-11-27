"""ETA (04 §4): remaining prep + travel along what's left of the polyline + 90 s handover.

Prep is the restaurant's declared `prep_min` in v1 (v3 replaces it with the measured average of
its own last 20 orders — measured from our history, no model). Travel speed is the rider's own:
a sim's fixed `speed_kmh`, a real rider's last reported speed clamped to 12–30 km/h (22 without
one). `method` is `line` when the leg is a straight-line fallback; the UI shows that as "≈".
"""

import datetime as dt
from dataclasses import dataclass

from app.models import Order, OrderStatus, RiderLeg
from app.services import routing
from app.services.orders import HANDOVER_S

S = OrderStatus
DEFAULT_KMH = 22.0


@dataclass(frozen=True)
class Eta:
    eta_s: int
    method: str
    phase: str  # cooking | to_restaurant | to_customer

    def as_event(self, order_id: str) -> dict:
        return {
            "order_id": order_id,
            "eta_s": self.eta_s,
            "method": self.method,
            "phase": self.phase,
        }


def speed_mps(is_sim: bool, speed_kmh: float, reported_mps: float | None) -> float:
    if is_sim:
        return speed_kmh / 3.6
    if reported_mps is None or reported_mps <= 0.5:
        return DEFAULT_KMH / 3.6
    return min(max(reported_mps, 12 / 3.6), 30 / 3.6)


def remaining_on_leg(leg: RiderLeg, position: tuple[float, float] | None) -> float:
    points = routing.decode(leg.polyline)
    cum = routing.cumulative(points)
    if position is None:
        return cum[-1]
    return max(0.0, cum[-1] - routing.project(points, cum, position))


def compute(
    order: Order,
    *,
    prep_min: int,
    leg: RiderLeg | None,
    position: tuple[float, float] | None,
    speed: float,
    now: dt.datetime,
) -> Eta | None:
    if order.status not in (S.placed, S.accepted, S.preparing, S.ready, S.picked_up):
        return None
    # The restaurant → drop ride, from the quote's road distance, at the rider's speed.
    drop_ride = order.distance_m / speed
    method = str(leg.method) if leg is not None else str(order.route_method)
    if order.status == S.picked_up and leg is not None:
        travel = remaining_on_leg(leg, position) / speed
        return Eta(round(travel + HANDOVER_S), method, "to_customer")
    started = order.accepted_at or order.placed_at or now
    remaining_prep = 0.0
    if order.status in (S.placed, S.accepted, S.preparing):
        remaining_prep = max(0.0, prep_min * 60 - (now - started).total_seconds())
        if order.status == S.placed:
            remaining_prep = prep_min * 60
    to_restaurant = 0.0
    if leg is not None and leg.kind == "to_restaurant" and leg.arrived_at is None:
        to_restaurant = remaining_on_leg(leg, position) / speed
    wait = max(remaining_prep, to_restaurant)
    phase = "cooking" if order.status in (S.placed, S.accepted, S.preparing) else "to_restaurant"
    return Eta(round(wait + drop_ride + HANDOVER_S), method, phase)
