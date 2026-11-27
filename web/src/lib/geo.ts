// Polyline maths in the browser — the mirror of api/app/services/routing.py. Display only: the web
// never decides a distance, fee or ETA that matters (05 §2).
export type LatLng = [number, number];

export function decode(polyline: string): LatLng[] {
  const points: LatLng[] = [];
  let i = 0;
  let lat = 0;
  let lng = 0;
  while (i < polyline.length) {
    for (let axis = 0; axis < 2; axis++) {
      let shift = 0;
      let result = 0;
      let b: number;
      do {
        b = polyline.charCodeAt(i++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (axis === 0) lat += delta;
      else lng += delta;
    }
    points.push([lat / 1e5, lng / 1e5]);
  }
  return points;
}

const R = 6_371_000;
const rad = (d: number) => (d * Math.PI) / 180;

export function haversine(a: LatLng, b: LatLng): number {
  const dLat = rad(b[0] - a[0]);
  const dLng = rad(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function bearing(a: LatLng, b: LatLng): number {
  const y = Math.sin(rad(b[1] - a[1])) * Math.cos(rad(b[0]));
  const x =
    Math.cos(rad(a[0])) * Math.sin(rad(b[0])) -
    Math.sin(rad(a[0])) * Math.cos(rad(b[0])) * Math.cos(rad(b[1] - a[1]));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

export function cumulative(points: LatLng[]): number[] {
  const out = [0];
  for (let i = 1; i < points.length; i++) out.push(out[i - 1] + haversine(points[i - 1], points[i]));
  return out;
}

/** The part of the line from `from` metres to `to` metres (for drawing a route as it grows). */
export function slice(points: LatLng[], cum: number[], to: number): LatLng[] {
  if (points.length < 2) return points;
  const out: LatLng[] = [points[0]];
  for (let i = 1; i < points.length; i++) {
    if (cum[i] <= to) {
      out.push(points[i]);
      continue;
    }
    const seg = cum[i] - cum[i - 1];
    const t = seg > 0 ? (to - cum[i - 1]) / seg : 0;
    out.push([points[i - 1][0] + (points[i][0] - points[i - 1][0]) * t, points[i - 1][1] + (points[i][1] - points[i - 1][1]) * t]);
    break;
  }
  return out;
}

/** Distance along the line of the point on it nearest to `p`. */
export function project(points: LatLng[], cum: number[], p: LatLng): number {
  if (points.length < 2) return 0;
  const k = Math.cos(rad(p[0]));
  let best = Infinity;
  let along = 0;
  for (let i = 1; i < points.length; i++) {
    const ax = points[i - 1][1] * k;
    const ay = points[i - 1][0];
    const dx = points[i][1] * k - ax;
    const dy = points[i][0] - ay;
    const L2 = dx * dx + dy * dy;
    const t = L2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[1] * k - ax) * dx + (p[0] - ay) * dy) / L2));
    const qx = ax + t * dx;
    const qy = ay + t * dy;
    const d = (p[1] * k - qx) ** 2 + (p[0] - qy) ** 2;
    if (d < best) {
      best = d;
      along = cum[i - 1] + t * (cum[i] - cum[i - 1]);
    }
  }
  return along;
}

export function lerp(a: LatLng, b: LatLng, t: number): LatLng {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/** Shortest-turn interpolation between two headings in degrees. */
export function lerpAngle(a: number, b: number, t: number): number {
  const d = ((((b - a) % 360) + 540) % 360) - 180;
  return (a + d * t + 360) % 360;
}

/** Koramangala / HSR, the seeded neighbourhood. */
export const AREA_CENTRE: LatLng = [12.9285, 77.6295];
export const DEFAULT_PIN = { lat: 12.9352, lng: 77.6195, label: "Koramangala 5th Block", line: "Koramangala 5th Block, Bengaluru" };
