"use client";

// MapLibre + OpenFreeMap (no key, no quota), loaded only on map pages. The signature motion lives
// here (04-ui-mockups "Rider glide + Route draw"): a rider marker eases between GPS fixes over
// their time gap (max 3 s) with requestAnimationFrame and turns to its heading; a new route draws
// itself from start to end in 900 ms; the drop pin drops with a spring. Reduced motion: markers
// jump, routes appear.
import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoJSONSource, Map as MlMap, Marker as MlMarker } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { cumulative, decode, lerp, lerpAngle, slice, type LatLng } from "@/lib/geo";

const LIGHT = process.env.NEXT_PUBLIC_MAP_STYLE || "https://tiles.openfreemap.org/styles/liberty";
const DARK = process.env.NEXT_PUBLIC_MAP_STYLE_DARK || "https://tiles.openfreemap.org/styles/dark";
const GLIDE_MAX_MS = 3000;
const DRAW_MS = 900;

export type MapMarker = {
  id: string;
  lat: number;
  lng: number;
  kind: "restaurant" | "drop" | "rider" | "dot";
  heading?: number | null;
  color?: string;
  sim?: boolean;
  busy?: boolean;
  title?: string;
  onClick?: () => void;
};
export type MapRoute = { id: string; polyline: string; color?: string; dashed?: boolean; draw?: boolean };

type Props = {
  label: string;
  dark?: boolean;
  center: LatLng;
  zoom?: number;
  markers?: MapMarker[];
  routes?: MapRoute[];
  trail?: LatLng[];
  fit?: LatLng[];
  fitKey?: string;
  draggable?: { lat: number; lng: number; onDragEnd: (lat: number, lng: number) => void };
  radarAt?: LatLng | null;
  interactive?: boolean;
  className?: string;
  children?: React.ReactNode;
};

const reduced = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function riderSvg(color = "#FF7A59") {
  return `<svg viewBox="-20 -20 40 40" width="40" height="40" aria-hidden="true"><g class="rot">
  <circle r="17" fill="${color}" stroke="#fff" stroke-width="3"/>
  <path d="M0 -12 L5 -5 L-5 -5 Z" fill="#fff"/>
  <g fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"><circle cx="-6" cy="5" r="3"/><circle cx="6" cy="5" r="3"/><path d="M-6 5 L-2 -2 L4 -2 L6 5"/></g></g></svg>`;
}

function pinSvg(color = "#7B5CFF") {
  return `<svg viewBox="0 0 34 44" width="34" height="44" aria-hidden="true"><path d="M17 43 C17 43 2 26 2 16 A15 15 0 1 1 32 16 C32 26 17 43 17 43Z" fill="${color}" stroke="#fff" stroke-width="3"/><circle cx="17" cy="16" r="6" fill="#fff"/></svg>`;
}

type Live = {
  marker: MlMarker;
  look: string;
  el: HTMLElement;
  pos: LatLng;
  heading: number;
  from: LatLng;
  to: LatLng;
  fromH: number;
  toH: number;
  start: number;
  dur: number;
  lastUpdate: number;
};

export default function LiveMap({
  label,
  dark,
  center,
  zoom = 14,
  markers = [],
  routes = [],
  trail,
  fit,
  fitKey,
  draggable,
  radarAt,
  interactive = true,
  className,
  children,
}: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const lib = useRef<typeof import("maplibre-gl") | null>(null);
  const live = useRef(new Map<string, Live>());
  const drawn = useRef(new Map<string, string>());
  const pin = useRef<MlMarker | null>(null);
  const radar = useRef<MlMarker | null>(null);
  const raf = useRef<number | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  // create the map once
  useEffect(() => {
    let cancelled = false;
    const markersLive = live.current;
    const routesDrawn = drawn.current;
    (async () => {
      try {
        const ml = await import("maplibre-gl");
        if (cancelled || !box.current) return;
        lib.current = ml;
        const m = new ml.Map({
          container: box.current,
          style: dark ? DARK : LIGHT,
          center: [center[1], center[0]],
          zoom,
          attributionControl: { compact: true },
          interactive,
          cooperativeGestures: false,
          fadeDuration: 0,
        });
        m.on("load", () => {
          if (cancelled) return;
          // A small map starts with the attribution folded to its (i) button, so it hides no pin.
          if ((box.current?.clientHeight ?? 0) < 400) box.current?.querySelectorAll(".maplibregl-compact-show").forEach((e) => e.classList.remove("maplibregl-compact-show"));
          setReady(true);
        });
        m.on("error", () => undefined);
        map.current = m;
        if (process.env.NODE_ENV !== "production") (window as unknown as { __maps?: MlMap[] }).__maps = [...((window as unknown as { __maps?: MlMap[] }).__maps ?? []), m];
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      if (raf.current) cancelAnimationFrame(raf.current);
      map.current?.remove();
      map.current = null;
      markersLive.clear();
      routesDrawn.clear();
    };
    // the map is created once; later props are applied by the effects below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // routes: a white casing under a coloured line; new ones draw themselves
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const ids = new Set(routes.map((r) => `route-${r.id}`));
    for (const [id] of drawn.current) {
      if (!ids.has(id)) {
        for (const layer of [`${id}-line`, `${id}-case`]) if (m.getLayer(layer)) m.removeLayer(layer);
        if (m.getSource(id)) m.removeSource(id);
        drawn.current.delete(id);
      }
    }
    for (const r of routes) {
      const id = `route-${r.id}`;
      if (drawn.current.get(id) === r.polyline) continue;
      const pts = decode(r.polyline);
      const cum = cumulative(pts);
      const geo = (coords: LatLng[]) => ({
        type: "Feature" as const,
        properties: {},
        geometry: { type: "LineString" as const, coordinates: coords.map(([a, b]) => [b, a]) },
      });
      const animate = r.draw !== false && !reduced() && pts.length > 1;
      const first = animate ? [pts[0], pts[0]] : pts;
      if (m.getSource(id)) (m.getSource(id) as GeoJSONSource).setData(geo(first));
      else {
        m.addSource(id, { type: "geojson", data: geo(first) });
        m.addLayer({
          id: `${id}-case`,
          type: "line",
          source: id,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#ffffff", "line-width": 11, "line-opacity": r.dashed ? 0 : 0.95 },
        });
        m.addLayer({
          id: `${id}-line`,
          type: "line",
          source: id,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": r.color ?? "#7B5CFF",
            "line-width": r.dashed ? 4 : 7,
            ...(r.dashed ? { "line-dasharray": [1, 2] } : {}),
          },
        });
      }
      drawn.current.set(id, r.polyline);
      if (animate) {
        const start = performance.now();
        const step = (now: number) => {
          const t = Math.min(1, (now - start) / DRAW_MS);
          const eased = 1 - Math.pow(1 - t, 3);
          const src = m.getSource(id) as GeoJSONSource | undefined;
          if (!src) return;
          src.setData(geo(slice(pts, cum, eased * cum[cum.length - 1])));
          if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }
    }
  }, [ready, routes]);

  // the rider's trail
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const data = {
      type: "Feature" as const,
      properties: {},
      geometry: { type: "LineString" as const, coordinates: (trail ?? []).map(([a, b]) => [b, a]) },
    };
    if (m.getSource("trail")) (m.getSource("trail") as GeoJSONSource).setData(data);
    else if (trail && trail.length > 1) {
      m.addSource("trail", { type: "geojson", data });
      m.addLayer({
        id: "trail-line",
        type: "line",
        source: "trail",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#FF7A59", "line-width": 4, "line-opacity": 0.75 },
      });
    }
  }, [ready, trail]);

  // markers; riders glide between updates
  useEffect(() => {
    const m = map.current;
    const ml = lib.current;
    if (!ready || !m || !ml) return;
    const now = performance.now();
    const seen = new Set<string>();
    for (const mk of markers) {
      seen.add(mk.id);
      const target: LatLng = [mk.lat, mk.lng];
      const heading = mk.heading ?? 0;
      const look = `${mk.kind}|${mk.color ?? ""}|${mk.sim ? 1 : 0}|${mk.busy ? 1 : 0}|${mk.title ?? ""}`;
      const existing = live.current.get(mk.id);
      if (existing && existing.look !== look) {
        // colour / sim ring / title changed: restyle in place, keep gliding
        existing.look = look;
        paint(existing.el, mk);
        rotate(existing.el, existing.heading);
      }
      if (existing) {
        if (mk.kind === "rider" && !reduced()) {
          existing.from = existing.pos;
          existing.fromH = existing.heading;
          existing.to = target;
          existing.toH = heading;
          existing.start = now;
          existing.dur = Math.min(GLIDE_MAX_MS, Math.max(300, now - existing.lastUpdate));
        } else {
          existing.pos = existing.from = existing.to = target;
          existing.heading = existing.toH = heading;
          existing.marker.setLngLat([target[1], target[0]]);
          rotate(existing.el, heading);
        }
        existing.lastUpdate = now;
        continue;
      }
      const el = document.createElement("div");
      paint(el, mk);
      if (mk.onClick) {
        el.style.cursor = "pointer";
        el.addEventListener("click", mk.onClick);
      }
      const marker = new ml.Marker({ element: el, anchor: mk.kind === "drop" ? "bottom" : "center" })
        .setLngLat([target[1], target[0]])
        .addTo(m);
      rotate(el, heading);
      live.current.set(mk.id, {
        marker,
        look,
        el,
        pos: target,
        heading,
        from: target,
        to: target,
        fromH: heading,
        toH: heading,
        start: now,
        dur: 0,
        lastUpdate: now,
      });
    }
    for (const [id, l] of live.current) {
      if (!seen.has(id)) {
        l.marker.remove();
        live.current.delete(id);
      }
    }
    if (raf.current === null) {
      const tick = (t: number) => {
        for (const l of live.current.values()) {
          if (l.dur <= 0 || (l.pos[0] === l.to[0] && l.pos[1] === l.to[1])) continue;
          const k = Math.min(1, (t - l.start) / l.dur);
          l.pos = lerp(l.from, l.to, k);
          l.heading = lerpAngle(l.fromH, l.toH, k);
          l.marker.setLngLat([l.pos[1], l.pos[0]]);
          rotate(l.el, l.heading);
        }
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);
    }
  }, [ready, markers]);

  // fit the camera when the set of things worth seeing changes
  useEffect(() => {
    const m = map.current;
    const ml = lib.current;
    if (!ready || !m || !ml || !fit || fit.length === 0) return;
    if (fit.length === 1) {
      m.easeTo({ center: [fit[0][1], fit[0][0]], duration: reduced() ? 0 : 600 });
      return;
    }
    const b = new ml.LngLatBounds();
    fit.forEach(([a, c]) => b.extend([c, a]));
    // extra room at the top: the status pill sits there
    m.fitBounds(b, { padding: { top: 72, bottom: 48, left: 48, right: 48 }, maxZoom: 16, duration: reduced() ? 0 : 700 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, fitKey]);

  // a draggable delivery pin
  useEffect(() => {
    const m = map.current;
    const ml = lib.current;
    if (!ready || !m || !ml) return;
    if (!draggable) {
      pin.current?.remove();
      pin.current = null;
      return;
    }
    if (!pin.current) {
      const el = document.createElement("div");
      el.className = "marker-pin drop";
      el.innerHTML = pinSvg();
      el.setAttribute("aria-label", "Delivery pin, drag to move");
      pin.current = new ml.Marker({ element: el, anchor: "bottom", draggable: true })
        .setLngLat([draggable.lng, draggable.lat])
        .addTo(m);
      pin.current.on("dragend", () => {
        const p = pin.current!.getLngLat();
        dragRef.current?.(p.lat, p.lng);
      });
    } else {
      pin.current.setLngLat([draggable.lng, draggable.lat]);
    }
    m.easeTo({ center: [draggable.lng, draggable.lat], duration: reduced() ? 0 : 500 });
  }, [ready, draggable?.lat, draggable?.lng, draggable]);
  const dragRef = useRef(draggable?.onDragEnd);
  dragRef.current = draggable?.onDragEnd;

  // radar ping from the restaurant while a rider is being found
  useEffect(() => {
    const m = map.current;
    const ml = lib.current;
    if (!ready || !m || !ml) return;
    radar.current?.remove();
    radar.current = null;
    if (radarAt && !reduced()) {
      const el = document.createElement("div");
      el.className = "radar";
      radar.current = new ml.Marker({ element: el }).setLngLat([radarAt[1], radarAt[0]]).addTo(m);
    }
  }, [ready, radarAt]);

  return (
    <div className={`map-wrap ${className ?? ""}`} role="region" aria-label={label}>
      <div ref={box} style={{ position: "absolute", inset: 0 }} />
      {!ready && !failed && <div className="skeleton" aria-hidden="true" style={{ position: "absolute", inset: 0, borderRadius: 0 }} />}
      {failed && (
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", padding: 16 }}>
          <p className="muted">The map couldn&apos;t load. Everything else still works.</p>
        </div>
      )}
      {children}
    </div>
  );
}

function paint(el: HTMLElement, mk: MapMarker) {
  el.title = mk.title ?? "";
  if (mk.kind === "rider") {
    el.className = `marker-rider${mk.sim ? " sim" : ""}${mk.busy ? " busy" : ""}`;
    el.innerHTML = riderSvg(mk.color);
  } else if (mk.kind === "drop") {
    el.className = "marker-pin drop";
    el.innerHTML = pinSvg(mk.color);
  } else if (mk.kind === "restaurant") {
    el.className = "marker-rest";
    el.textContent = "🍳";
  } else {
    el.className = `marker-dot${mk.sim ? " sim" : ""}`;
    el.style.background = mk.color ?? "#2ECC71";
    el.style.color = mk.color ?? "#2ECC71";
  }
}

function rotate(el: HTMLElement, heading: number) {
  const g = el.querySelector<SVGGElement>(".rot");
  if (g) g.setAttribute("transform", `rotate(${heading})`);
}
