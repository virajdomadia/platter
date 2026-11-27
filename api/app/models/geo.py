"""Points in and out of PostGIS without shapely: WKT in, (E)WKB out."""

import struct
from typing import Any

from geoalchemy2 import WKTElement
from geoalchemy2.elements import WKBElement


def make_point(lat: float, lng: float) -> WKTElement:
    return WKTElement(f"POINT({lng:.7f} {lat:.7f})", srid=4326)


def latlng(value: Any) -> tuple[float, float]:
    """(lat, lng) from a geography point as asyncpg returns it (EWKB hex or bytes)."""
    if isinstance(value, WKTElement):
        lng, lat = value.data.split("(")[1].rstrip(")").split()
        return float(lat), float(lng)
    if isinstance(value, WKBElement):
        raw = value.data
    else:
        raw = value
    if isinstance(raw, str):
        raw = bytes.fromhex(raw)
    raw = bytes(raw)
    endian = "<" if raw[0] == 1 else ">"
    (gtype,) = struct.unpack(endian + "I", raw[1:5])
    offset = 5 + (4 if gtype & 0x20000000 else 0)
    x, y = struct.unpack(endian + "dd", raw[offset : offset + 16])
    return y, x
