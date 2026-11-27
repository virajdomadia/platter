"use client";

// S9 — live operations (R9). Stat tiles, one big map with every restaurant, active order and rider
// (riders glide on the 2 s `riders` frames), and the live-orders ledger with reassign.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Map, type MapMarker, type MapRoute } from "@/components/map/Map";
import { RoleBar } from "@/components/ui/RoleBar";
import { api, errorMessage, type AdminMap, type AdminOrder, type AdminRider } from "@/lib/api";
import { age, inr, minutes, STATUS_LABEL } from "@/lib/format";
import { AREA_CENTRE, haversine, type LatLng } from "@/lib/geo";
import { useEventStream } from "@/lib/stream";
import { ReassignPicker } from "./ReassignPicker";
import "./admin.css";

const RIDER_COLOR: Record<AdminRider["status"], string> = {
  busy: "#FF7A59",
  available: "#2ECC71",
  offline: "#9A94B0",
};
const REASSIGNABLE = new Set<AdminOrder["status"]>(["accepted", "preparing", "ready"]);

type FocusKind = "order" | "rider" | "all";
type Focus = { kind: FocusKind; id: string; n: number };

export function AdminScreen() {
  const [data, setData] = useState<AdminMap | null>(null);
  const [fetchedAt, setFetchedAt] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>({ kind: "all", id: "", n: 0 });
  const [picking, setPicking] = useState<AdminOrder | null>(null);
  const now = useNow(1000);

  const load = useCallback(async () => {
    try {
      const d = await api<AdminMap>("/admin/map");
      setData(d);
      setFetchedAt(Date.now());
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const debounce = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(debounce.current), []);
  const stream = useEventStream("/api/admin/events", (name, payload) => {
    if (name === "riders") {
      const riders = (payload as { riders?: AdminRider[] } | null)?.riders;
      if (riders) setData((d) => (d ? { ...d, riders } : d));
      return;
    }
    if (name === "status" || name === "route" || name === "rider_assigned" || name === "rider_reassigned" || name === "reconnect") {
      window.clearTimeout(debounce.current);
      debounce.current = window.setTimeout(() => void load(), 400);
    }
  });
  const live = stream.connected && !stream.stale;

  const select = useCallback((kind: FocusKind, id: string) => {
    setFocus((f) => ({ kind, id, n: f.n + 1 }));
  }, []);

  return (
    <div className="ad">
      <div className="ad-top">
        <RoleBar title="Live operations" subtitle="Koramangala · HSR Layout" who="👑 Admin">
          <span className={`chip ${live ? "live" : "peach"}`} role="status">
            {live ? "Live" : "Reconnecting…"}
          </span>
        </RoleBar>
      </div>

      {!data && !loadError && <Skeletons />}
      {!data && loadError && (
        <section className="tile peach ad-full" role="alert">
          <h2>Couldn&apos;t load the live map</h2>
          <p style={{ marginTop: 6 }}>{loadError}</p>
          <button className="btn" style={{ marginTop: 12 }} onClick={() => void load()}>
            Retry
          </button>
        </section>
      )}
      {data && (
        <Board
          data={data}
          elapsed={Math.max(0, (now - fetchedAt) / 1000)}
          focus={focus}
          onSelect={select}
          onPick={setPicking}
        />
      )}

      {picking && (
        <ReassignPicker
          order={picking}
          onClose={() => setPicking(null)}
          onDone={() => {
            setPicking(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

function Skeletons() {
  return (
    <>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="skeleton ad-stat" aria-hidden="true" />
      ))}
      <div className="skeleton ad-map" aria-hidden="true" />
      <div className="skeleton ad-ledger" aria-hidden="true" />
      <p className="sr-only" role="status">
        Loading the live map…
      </p>
    </>
  );
}

function Board({
  data,
  elapsed,
  focus,
  onSelect,
  onPick,
}: {
  data: AdminMap;
  elapsed: number;
  focus: Focus;
  onSelect: (kind: FocusKind, id: string) => void;
  onPick: (o: AdminOrder) => void;
}) {
  const { orders, riders, restaurants, today } = data;
  const free = riders.filter((r) => r.status === "available").length;
  const stuck = orders.filter((o) => o.stuck).length;
  const focusedOrder = focus.kind === "order" ? focus.id : null;
  const focusedRider = focus.kind === "rider" ? focus.id : null;

  const markers = useMemo<MapMarker[]>(() => {
    const out: MapMarker[] = restaurants.map((r) => ({
      id: `rest-${r.id}`,
      kind: "restaurant",
      lat: r.lat,
      lng: r.lng,
      title: r.name,
    }));
    for (const o of orders) {
      const on = o.id === focusedOrder;
      out.push({
        id: `drop-${o.id}`,
        kind: "drop",
        lat: o.drop.lat,
        lng: o.drop.lng,
        color: on ? "#FF7A59" : "#7B5CFF",
        title: `${o.number} · drop`,
        onClick: () => onSelect("order", o.id),
      });
    }
    for (const r of riders) {
      if (r.lat === null || r.lng === null) continue;
      out.push({
        id: `rider-${r.id}`,
        kind: "rider",
        lat: r.lat,
        lng: r.lng,
        heading: r.heading,
        color: RIDER_COLOR[r.status],
        sim: r.is_sim,
        busy: r.status === "busy",
        title: `${r.name} · ${r.is_sim ? "simulated" : "real (phone)"}${r.current_order ? ` · ${r.current_order}` : ""}`,
        onClick: () => onSelect("rider", r.id),
      });
    }
    return out;
  }, [restaurants, orders, riders, focusedOrder, onSelect]);

  const routes = useMemo<MapRoute[]>(() => {
    const out: MapRoute[] = [];
    for (const o of orders) {
      const kind = o.status === "picked_up" ? "to_customer" : "to_restaurant";
      const leg = o.legs.find((l) => l.kind === kind);
      if (!leg) continue;
      out.push({ id: `${o.id}-${kind}`, polyline: leg.polyline, color: "#7B5CFF", dashed: kind === "to_restaurant" });
    }
    return out;
  }, [orders]);

  // the camera: everything at first, then whatever was clicked (read only when fitKey changes)
  const fit = ((): LatLng[] => {
    if (focus.kind === "order") {
      const o = orders.find((x) => x.id === focus.id);
      if (o) {
        const pts: LatLng[] = [
          [o.restaurant.lat, o.restaurant.lng],
          [o.drop.lat, o.drop.lng],
        ];
        const r = riders.find((x) => x.id === o.rider_id);
        if (r && r.lat !== null && r.lng !== null) pts.push([r.lat, r.lng]);
        return pts;
      }
    }
    if (focus.kind === "rider") {
      const r = riders.find((x) => x.id === focus.id);
      if (r && r.lat !== null && r.lng !== null) return [[r.lat, r.lng]];
    }
    // the service area (Koramangala & HSR) and what is moving in it, not every kitchen in town
    const near = (p: LatLng) => haversine(p, AREA_CENTRE) < SERVICE_M;
    const pts = [...restaurants.map((r): LatLng => [r.lat, r.lng]), ...orders.map((o): LatLng => [o.drop.lat, o.drop.lng])].filter(near);
    return pts.length ? pts : [AREA_CENTRE];
  })();
  const fitKey = `${focus.kind}-${focus.id}-${focus.n}-${restaurants.length}`;

  return (
    <>
      <section className="tile lav ad-stat spring">
        <b className="num">{orders.length}</b>
        <small>active orders</small>
      </section>
      <section className="tile mint ad-stat spring">
        <b className="num">{free}</b>
        <small>riders free · {riders.length} total</small>
      </section>
      <section className={`tile peach ad-stat spring ${stuck ? "ad-alert" : ""}`}>
        <b className="num">{stuck}</b>
        <small>stuck: flagged in the list</small>
      </section>
      <section className="tile ink ad-stat ad-today spring">
        <span className="label">Today</span>
        <p className="num">
          <b>{today.orders}</b> orders · <b>{today.delivered}</b> delivered
        </p>
        <p className="num">
          <b>{inr(today.revenue_paise)}</b> revenue · avg delivery <b>{today.avg_delivery_s != null ? age(today.avg_delivery_s) : "—"}</b>
        </p>
      </section>

      <section className="tile flush ad-map">
        <Map label="Live map of restaurants, orders and riders" center={AREA_CENTRE} zoom={13} markers={markers} routes={routes} fit={fit} fitKey={fitKey}>
          <div className="ad-legend" aria-label="Map legend">
            <span>
              <i className="busy" style={{ background: RIDER_COLOR.busy }} />
              busy (square badge)
            </span>
            <span>
              <i style={{ background: RIDER_COLOR.available }} />
              available
            </span>
            <span>
              <i style={{ background: RIDER_COLOR.offline }} />
              offline
            </span>
            <span className="muted">dashed ring = simulated rider · solid = a real phone sharing GPS</span>
          </div>
          {focus.kind !== "all" && (
            <button type="button" className="btn small white ad-reset" onClick={() => onSelect("all", "")}>
              Show everything
            </button>
          )}
        </Map>
      </section>

      <section className="tile ad-ledger" aria-labelledby="ledger-h">
        <h2 id="ledger-h">Live orders</h2>
        {orders.length === 0 ? (
          <p className="muted ad-empty">
            No active orders right now. Sim customers order while someone watches this map; or place one as the demo customer.
          </p>
        ) : (
          <div className="ad-scroll">
            <table className="ad-table">
              <colgroup>
                <col style={{ width: 74 }} />
                <col />
                <col style={{ width: 90 }} />
                <col style={{ width: 64 }} />
                <col style={{ width: 120 }} />
                <col style={{ width: 96 }} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Order</th>
                  <th scope="col">Restaurant</th>
                  <th scope="col">Status</th>
                  <th scope="col">Age</th>
                  <th scope="col">Rider</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <Row
                    key={o.id}
                    o={o}
                    elapsed={elapsed}
                    on={o.id === focusedOrder || (focusedRider !== null && o.rider_id === focusedRider)}
                    onSelect={() => onSelect("order", o.id)}
                    onPick={() => onPick(o)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function Row({
  o,
  elapsed,
  on,
  onSelect,
  onPick,
}: {
  o: AdminOrder;
  elapsed: number;
  on: boolean;
  onSelect: () => void;
  onPick: () => void;
}) {
  const tone = o.status === "picked_up" ? "mint" : o.status === "placed" ? "peach" : o.status === "ready" ? "lemon" : "lav";
  const stuck =
    o.stuck === "unaccepted"
      ? `unaccepted ${minutes(o.status_age_s + elapsed)} min`
      : o.stuck === "no_rider"
        ? "no rider"
        : o.stuck === "not_picked_up"
          ? "not picked up"
          : o.stuck === "kitchen_late"
            ? "kitchen late"
            : null;
  return (
    <tr className={`${on ? "on" : ""} ${stuck ? "stuck" : ""}`} onClick={onSelect}>
      <td>
        <button
          type="button"
          className="ad-link num"
          aria-pressed={on}
          title="Show on the map"
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
        >
          {o.number}
        </button>
      </td>
      <td title={o.restaurant_name}>{o.restaurant_name}</td>
      <td>
        <span className={`chip ${tone}`}>{STATUS_LABEL[o.status] ?? o.status}</span>
      </td>
      <td className={`num ${stuck ? "ad-stuck" : ""}`}>{age(o.age_s + elapsed)}</td>
      <td title={stuck ?? o.rider_name ?? undefined}>
        {stuck ? <span className="ad-stuck"><span aria-hidden="true">⚠ </span>{stuck}</span> : (o.rider_name ?? "—")}
      </td>
      <td>
        {REASSIGNABLE.has(o.status) && (
          <button
            type="button"
            className="btn small ghost"
            onClick={(e) => {
              e.stopPropagation();
              onPick();
            }}
          >
            {o.rider_id ? "Reassign" : "Assign"}
          </button>
        )}
      </td>
    </tr>
  );
}

const SERVICE_M = 4000;

function useNow(every: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), every);
    return () => window.clearInterval(t);
  }, [every]);
  return now;
}
