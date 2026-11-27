"""04 §12 test_eta: projection onto the polyline and the remaining length; the `line` method when
OSRM fails; the ETA falls as the rider rides."""

import datetime as dt

import pytest

from app.core import clock
from app.services import eta, routing

LINE = [(12.9300, 77.6200), (12.9300, 77.6300), (12.9400, 77.6300)]  # east, then north


def test_polyline_round_trip():
    pts = [(12.93456, 77.61823), (12.93511, 77.61902), (12.9349, 77.6201)]
    assert routing.decode(routing.encode(pts)) == pts
    # Google's reference example
    assert (
        routing.encode([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])
        == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    )


def test_projection_and_remaining_length():
    cum = routing.cumulative(LINE)
    first = routing.haversine(LINE[0], LINE[1])
    total = cum[-1]
    # a point just off the first segment, halfway along it
    p = (12.9301, 77.6250)
    along = routing.project(LINE, cum, p)
    assert along == pytest.approx(first / 2, rel=0.01)
    # on the corner → exactly the first segment
    assert routing.project(LINE, cum, LINE[1]) == pytest.approx(first, rel=1e-6)
    # beyond the end clamps to the end
    assert routing.project(LINE, cum, (12.95, 77.63)) == pytest.approx(total)
    point, heading = routing.point_at(LINE, cum, first + 10)
    assert heading == 0 and point[1] == pytest.approx(77.63)


def test_speed_is_clamped():
    assert eta.speed_mps(True, 22.0, None) == pytest.approx(22 / 3.6)
    assert eta.speed_mps(False, 22.0, None) == pytest.approx(22 / 3.6)
    assert eta.speed_mps(False, 22.0, 50.0) == pytest.approx(30 / 3.6)
    assert eta.speed_mps(False, 22.0, 1.0) == pytest.approx(12 / 3.6)


async def test_osrm_failure_falls_back_to_a_line(monkeypatch):
    async def down(points):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(routing, "fetch_osrm", down)
    r = await routing.route(LINE[0], LINE[2])
    assert r.method == "line"
    assert r.distance_m == round(routing.haversine(LINE[0], LINE[2]) * 1.3)
    assert r.duration_s == round(r.distance_m / (22 / 3.6))
    assert routing.decode(r.polyline) == [LINE[0], LINE[2]]


async def test_osrm_route_is_used_when_it_answers(monkeypatch):
    async def up(points):  # type: ignore[no-untyped-def]
        return {"geometry": routing.encode(LINE), "distance": 2200.4, "duration": 310.6}

    monkeypatch.setattr(routing, "fetch_osrm", up)
    r = await routing.route(LINE[0], LINE[2])
    assert (r.method, r.distance_m, r.duration_s) == ("osrm", 2200, 311)


def test_eta_falls_as_the_rider_rides():
    from app.models import LegKind, Order, OrderStatus, RiderLeg, RouteMethod

    now = clock.now()
    leg = RiderLeg(
        kind=LegKind.to_customer,
        polyline=routing.encode(LINE),
        distance_m=round(routing.cumulative(LINE)[-1]),
        duration_s=400,
        method=RouteMethod.osrm,
        started_at=now,
    )
    order = Order(
        status=OrderStatus.picked_up, distance_m=leg.distance_m, route_method=RouteMethod.osrm
    )
    speed = 22 / 3.6
    at_start = eta.compute(order, prep_min=15, leg=leg, position=LINE[0], speed=speed, now=now)
    at_corner = eta.compute(order, prep_min=15, leg=leg, position=LINE[1], speed=speed, now=now)
    at_end = eta.compute(order, prep_min=15, leg=leg, position=LINE[2], speed=speed, now=now)
    assert at_start.phase == "to_customer" and at_start.method == "osrm"
    assert at_start.eta_s > at_corner.eta_s > at_end.eta_s == 90  # just the handover left

    cooking = Order(
        status=OrderStatus.preparing,
        distance_m=2000,
        route_method=RouteMethod.line,
        accepted_at=now - dt.timedelta(minutes=5),
    )
    e = eta.compute(cooking, prep_min=15, leg=None, position=None, speed=speed, now=now)
    assert e.phase == "cooking" and e.method == "line"
    assert e.eta_s == round(10 * 60 + 2000 / speed + 90)
