"""Discovery and address text (04 §4).

* Nearby restaurants: one PostGIS query — `ST_DWithin(loc, pin, 8000)` ordered by `ST_Distance`
  over the GIST index; ≤ 5 km is orderable, 5–8 km is shown greyed as "Too far".
* Photon geocoding, proxied so the browser never calls it directly: a Bengaluru bounding box,
  the API's User-Agent, and a 10-per-minute-per-IP limit. Photon down → the caller tells the user
  to drop the pin instead; reverse falls back to "lat, lng".
"""

import logging
import time
from collections import defaultdict, deque

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as s
from app.core.config import get_settings
from app.core.errors import ApiError
from app.models import Restaurant
from app.services import orders, views

log = logging.getLogger(__name__)

# Bengaluru (minLon, minLat, maxLon, maxLat)
BBOX = "77.45,12.83,77.78,13.10"
LIMIT_PER_MIN = 10
_hits: dict[str, deque[float]] = defaultdict(deque)


async def nearby(db: AsyncSession, lat: float, lng: float) -> list[s.RestaurantCard]:
    rows = (
        await db.execute(
            text(
                """
                with pin as (select ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography as p)
                select r.id, ST_Distance(r.loc, pin.p) as distance_m
                from restaurants r, pin
                where ST_DWithin(r.loc, pin.p, :shown)
                order by distance_m
                """
            ),
            {"lat": lat, "lng": lng, "shown": orders.SHOWN_RADIUS_M},
        )
    ).all()
    out = []
    for rid, distance in rows:
        r = await db.get(Restaurant, rid)
        assert r is not None  # noqa: S101
        out.append(views.restaurant_card(r, distance_m=round(distance)))
    # Orderable first (by distance), then closed, then too far — each by distance.
    rank = {None: 0, "closed": 1, "too_far": 2}
    out.sort(key=lambda c: (rank[c.reason], c.distance_m))
    return out


def rate_limit(ip: str) -> None:
    now = time.monotonic()
    hits = _hits[ip]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= LIMIT_PER_MIN:
        raise ApiError(429, "rate_limited", "Too many searches — try again in a minute")
    hits.append(now)


def _place(feature: dict) -> s.Place:
    p = feature.get("properties", {})
    lng, lat = feature["geometry"]["coordinates"]
    name = p.get("name") or p.get("street") or "Pinned place"
    street = " ".join(x for x in (p.get("housenumber"), p.get("street")) if x)
    parts = [
        x
        for x in (
            street if street != name else None,
            p.get("district"),
            p.get("locality"),
            p.get("city"),
        )
        if x
    ]
    return s.Place(label=name, line=", ".join(dict.fromkeys(parts)) or name, lat=lat, lng=lng)


async def _photon(path: str, params: dict) -> list[dict] | None:
    settings = get_settings()
    if settings.photon_url == "off":
        return None
    try:
        async with httpx.AsyncClient(
            timeout=4.0, headers={"User-Agent": settings.user_agent}
        ) as client:
            r = await client.get(f"{settings.photon_url}{path}", params=params)
        r.raise_for_status()
        return r.json().get("features", [])
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Photon failed (%s)", type(exc).__name__)
        return None


async def search(q: str, lat: float | None, lng: float | None) -> list[s.Place]:
    params: dict = {"q": q, "lang": "en", "limit": 6, "bbox": BBOX}
    if lat is not None and lng is not None:
        params.update({"lat": lat, "lon": lng})
    features = await _photon("/api", params)
    if features is None:
        raise ApiError(503, "geocoder_down", "Address search is down — drop the pin instead")
    return [_place(f) for f in features]


async def reverse(lat: float, lng: float) -> s.Place:
    features = await _photon("/reverse", {"lat": lat, "lon": lng, "lang": "en"})
    if features:
        return (
            _place(features[0])
            if features[0].get("geometry")
            else s.Place(label="Pinned location", line=f"{lat:.5f}, {lng:.5f}", lat=lat, lng=lng)
        )
    return s.Place(label="Pinned location", line=f"{lat:.5f}, {lng:.5f}", lat=lat, lng=lng)
