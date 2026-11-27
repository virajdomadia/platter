"""Legs: one OSRM route per leg, cached on `rider_legs`; a straight line × 1.3 when OSRM is down or
slow (04 §4). Plus the pure polyline maths every other service uses — encode / decode (Google,
precision 5), haversine, cumulative lengths, a point at a distance, projection onto the line.
No shapely: a leg is a few hundred points."""

import logging
import math
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

LatLng = tuple[float, float]

LINE_FACTOR = 1.3
LINE_SPEED_KMH = 22.0
OSRM_TIMEOUT_S = 3.0
EARTH_M = 6_371_000.0


@dataclass(frozen=True)
class Route:
    polyline: str
    distance_m: int
    duration_s: int
    method: str  # "osrm" | "line"


# --- polyline -------------------------------------------------------------------------------


def _encode_value(v: int) -> str:
    v = ~(v << 1) if v < 0 else v << 1
    out = []
    while v >= 0x20:
        out.append(chr((0x20 | (v & 0x1F)) + 63))
        v >>= 5
    out.append(chr(v + 63))
    return "".join(out)


def encode(points: list[LatLng]) -> str:
    out, plat, plng = [], 0, 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        out.append(_encode_value(ilat - plat))
        out.append(_encode_value(ilng - plng))
        plat, plng = ilat, ilng
    return "".join(out)


def decode(polyline: str) -> list[LatLng]:
    points: list[LatLng] = []
    i, lat, lng = 0, 0, 0
    while i < len(polyline):
        for axis in (0, 1):
            shift, result = 0, 0
            while True:
                b = ord(polyline[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lng += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


# --- distances --------------------------------------------------------------------------------


def haversine(a: LatLng, b: LatLng) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_M * math.asin(math.sqrt(h))


def bearing(a: LatLng, b: LatLng) -> int:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lng2 - lng1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lng2 - lng1)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360)


def cumulative(points: list[LatLng]) -> list[float]:
    out = [0.0]
    for i in range(1, len(points)):
        out.append(out[-1] + haversine(points[i - 1], points[i]))
    return out


def point_at(points: list[LatLng], cum: list[float], distance: float) -> tuple[LatLng, int]:
    """The point `distance` metres along the line, and the heading of that segment."""
    if len(points) == 1:
        return points[0], 0
    distance = max(0.0, min(distance, cum[-1]))
    i = 1
    while i < len(cum) - 1 and cum[i] < distance:
        i += 1
    seg = cum[i] - cum[i - 1]
    t = 0.0 if seg <= 0 else (distance - cum[i - 1]) / seg
    a, b = points[i - 1], points[i]
    p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return p, bearing(a, b)


def project(points: list[LatLng], cum: list[float], p: LatLng) -> float:
    """Distance along the line of the point on it nearest to `p` (segment projection on a local
    equirectangular plane — exact enough over a few km)."""
    if len(points) == 1:
        return 0.0
    k = math.cos(math.radians(p[0]))
    best_d, best_along = math.inf, 0.0
    for i in range(1, len(points)):
        ax, ay = points[i - 1][1] * k, points[i - 1][0]
        bx, by = points[i][1] * k, points[i][0]
        px, py = p[1] * k, p[0]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        qx, qy = ax + t * dx, ay + t * dy
        d = (px - qx) ** 2 + (py - qy) ** 2
        if d < best_d:
            best_d = d
            best_along = cum[i - 1] + t * (cum[i] - cum[i - 1])
    return best_along


def line_route(a: LatLng, b: LatLng) -> Route:
    distance = haversine(a, b) * LINE_FACTOR
    return Route(
        polyline=encode([a, b]),
        distance_m=round(distance),
        duration_s=round(distance / (LINE_SPEED_KMH / 3.6)),
        method="line",
    )


# --- OSRM -------------------------------------------------------------------------------------


async def fetch_osrm(points: list[LatLng]) -> dict | None:
    """One OSRM request, or None on any failure. Tests replace this function."""
    settings = get_settings()
    if settings.osrm_url == "off":
        return None
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    url = f"{settings.osrm_url}/route/v1/driving/{coords}"
    params = {"overview": "full", "geometries": "polyline", "steps": "false"}
    try:
        async with httpx.AsyncClient(
            timeout=OSRM_TIMEOUT_S, headers={"User-Agent": settings.user_agent}
        ) as client:
            r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        return data["routes"][0]
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("OSRM failed (%s); using a straight line", type(exc).__name__)
        return None


async def route(a: LatLng, b: LatLng) -> Route:
    found = await fetch_osrm([a, b])
    if not found:
        return line_route(a, b)
    return Route(
        polyline=found["geometry"],
        distance_m=round(found["distance"]),
        duration_s=round(found["duration"]),
        method="osrm",
    )
