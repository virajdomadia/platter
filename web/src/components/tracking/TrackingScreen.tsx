"use client";

// S5 — the hero. The map is the biggest tile: the route draws itself, the rider glides along it
// between fixes, a coral trail follows; the ETA rolls down; the status rail lights from the event
// log; tiles re-spring and change colour as the order moves (the page itself is the status).
// Everything arrives over one EventSource (`/api/orders/{id}/events`) — a reconnect replays what
// was missed from the durable log.
import Image from "next/image";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Map, type MapMarker, type MapRoute } from "@/components/map/Map";
import { api, errorMessage, type OrderOut } from "@/lib/api";
import { clock, etaLabel, inr, km, minutes, STATUS_LABEL } from "@/lib/format";
import { cumulative, decode, project, type LatLng } from "@/lib/geo";
import { useOrderStream } from "@/lib/stream";
import { toast } from "@/lib/toast";

const STEPS = [
  { status: "placed", icon: "🧾", label: "Placed" },
  { status: "accepted", icon: "✅", label: "Accepted" },
  { status: "preparing", icon: "🍳", label: "Cooking" },
  { status: "ready", icon: "🛍️", label: "Ready" },
  { status: "picked_up", icon: "🛵", label: "Picked up" },
  { status: "delivered", icon: "🏠", label: "Delivered" },
];
const ORDER = STEPS.map((s) => s.status);
const ENDED = new Set(["rejected", "cancelled", "expired"]);
const WEAK_AFTER_MS = 30_000;

export function TrackingScreen({ initial }: { initial: OrderOut }) {
  const { live, stream } = useOrderStream(initial);
  const o = live.order;
  const [now, setNow] = useState(() => Date.now());
  const [cancelling, setCancelling] = useState(false);
  const [trail, setTrail] = useState<LatLng[]>(() => initial.trail.map((p) => [p[0], p[1]] as LatLng));

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(t);
  }, []);

  // grow the trail from live fixes (reset when the rider changes)
  useEffect(() => {
    if (!live.fix) return;
    setTrail((t) => {
      const p: LatLng = [live.fix!.lat, live.fix!.lng];
      const last = t[t.length - 1];
      if (last && last[0] === p[0] && last[1] === p[1]) return t;
      return [...t.slice(-600), p];
    });
  }, [live.fix]);
  const [trailRider, setTrailRider] = useState(o.rider?.id);
  if (trailRider !== o.rider?.id) {
    // a reassigned rider starts a fresh trail
    setTrailRider(o.rider?.id);
    setTrail([]);
  }

  const status = o.status;
  const ended = ENDED.has(status);
  const delivered = status === "delivered";
  const leg = useMemo(() => {
    const kind = status === "picked_up" || delivered ? "to_customer" : "to_restaurant";
    return o.legs.filter((l) => l.kind === kind).at(-1) ?? null;
  }, [o.legs, status, delivered]);
  const findingRider = !o.rider && ["accepted", "preparing", "ready"].includes(status);
  const onTheRoad = !!o.rider && ["accepted", "preparing", "ready", "picked_up"].includes(status);
  const weak = onTheRoad && live.fixAt > 0 && now - live.fixAt > WEAK_AFTER_MS;
  const eta = live.eta;
  const close = eta && eta.eta_s <= 180;

  const remaining = useMemo(() => {
    if (!leg || !live.fix || status !== "picked_up") return null;
    const pts = decode(leg.polyline);
    const cum = cumulative(pts);
    return Math.max(0, cum[cum.length - 1] - project(pts, cum, [live.fix.lat, live.fix.lng]));
  }, [leg, live.fix, status]);

  const markers: MapMarker[] = [
    { id: "rest", kind: "restaurant", lat: o.restaurant.lat, lng: o.restaurant.lng, title: o.restaurant.name },
    { id: "drop", kind: "drop", lat: o.drop.lat, lng: o.drop.lng, title: "You" },
    ...(live.fix && !ended && !delivered
      ? [{ id: `rider-${o.rider?.id ?? "x"}`, kind: "rider" as const, lat: live.fix.lat, lng: live.fix.lng, heading: live.fix.heading, title: o.rider?.name }]
      : []),
  ];
  const routes: MapRoute[] = leg && !ended ? [{ id: leg.leg_id, polyline: leg.polyline, color: "#7B5CFF" }] : [];
  const fitPoints: LatLng[] = [[o.restaurant.lat, o.restaurant.lng], [o.drop.lat, o.drop.lng]];
  if (live.fix && !delivered) fitPoints.push([live.fix.lat, live.fix.lng]);
  if (leg && !ended) fitPoints.push(...decode(leg.polyline)); // the whole route, not just its ends

  const curIndex = ORDER.indexOf(status);
  const pill = ended
    ? STATUS_LABEL[status]
    : delivered
      ? "Delivered"
      : findingRider
        ? "Finding a rider…"
        : status === "picked_up"
          ? `${o.rider?.name.split(" ")[0]} is on the way`
          : status === "placed"
            ? "Waiting for the kitchen"
            : o.rider
              ? `${o.rider.name.split(" ")[0]} is heading to the kitchen`
              : "Cooking";

  const cancel = async () => {
    setCancelling(true);
    try {
      await api(`/orders/${o.id}/cancel`, { method: "POST" });
      toast("Order cancelled", `${o.number} won't be made.`, "ok");
    } catch (err) {
      toast("Couldn't cancel", errorMessage(err));
    } finally {
      setCancelling(false);
    }
  };

  return (
    <main id="main" className="page track">
      <div className="tile track-head spring">
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontSize: 18 }}>Order {o.number}</h1>
          <p className="muted" style={{ fontSize: 12 }}>
            {o.restaurant.name} → {o.drop.line} · {o.payment === "cod" ? "Cash on delivery" : "Paid online"}
          </p>
        </div>
        <div className="row" style={{ marginLeft: "auto", flexWrap: "wrap", justifyContent: "flex-end" }}>
          {!ended && !delivered && (stream.connected && !stream.stale ? <span className="chip mint live">Live</span> : <span className="chip peach">{stream.lastFrameAt ? "Reconnecting…" : "Connecting…"}</span>)}
          {status === "placed" && o.payment === "cod" && (
            <button className="btn small ghost" onClick={cancel} disabled={cancelling}>
              {cancelling ? "Cancelling…" : "Cancel order"}
            </button>
          )}
        </div>
      </div>

      <div className="tile flush track-map spring">
        <Map
          label={`Live map: ${o.restaurant.name} to your address${o.rider ? `, rider ${o.rider.name}` : ""}`}
          center={[o.drop.lat, o.drop.lng]}
          zoom={14}
          markers={markers}
          routes={routes}
          trail={status === "picked_up" ? trail : undefined}
          fit={fitPoints}
          fitKey={`${status}-${leg?.leg_id ?? ""}-${o.rider?.id ?? ""}`}
          radarAt={findingRider ? [o.restaurant.lat, o.restaurant.lng] : null}
        >
          <span className="map-pill">{pill}</span>
          {weak && <span className="map-pill" style={{ top: 56, background: "var(--peach)" }}>Rider&apos;s signal is weak. The map will catch up.</span>}
        </Map>
      </div>

      <div key={`eta-${close ? 1 : 0}-${status}`} className={`tile eta-tile colour-swap respring ${delivered ? "mint" : close ? "mint" : ended ? "peach" : "lav"}`}>
        {delivered ? (
          <>
            <b className="handover" aria-hidden="true">✓</b>
            <small>Delivered {o.timestamps.delivered ? `at ${clock(o.timestamps.delivered)}` : ""} · enjoy!</small>
          </>
        ) : ended ? (
          <>
            <b style={{ fontSize: 26 }}>{STATUS_LABEL[status]}</b>
            <small>{o.reject_reason ?? (status === "expired" ? "Payment wasn't completed in 15 minutes." : "This order won't be made.")}</small>
          </>
        ) : status === "pending_payment" ? (
          <>
            <b style={{ fontSize: 22 }}>Awaiting payment</b>
            <small>Finish paying in the Razorpay window. It is saved for 15 min.</small>
          </>
        ) : eta ? (
          <>
            <b className="num" aria-live="polite">
              {eta.method === "line" && <span style={{ fontSize: 26 }}>≈ </span>}
              <span className="roll"><span key={minutes(eta.eta_s)}>{minutes(eta.eta_s)}</span></span> min
            </b>
            <small>
              {eta.phase === "cooking" ? "kitchen is cooking" : eta.phase === "to_restaurant" ? "rider heading to the kitchen" : remaining !== null ? `${km(remaining)} to go` : "on the way to you"}
              {eta.method === "line" ? " · straight-line estimate" : ""}
            </small>
          </>
        ) : (
          <>
            <b className="num">{etaLabel(o.totals.distance_m / 6.1 + 15 * 60)}</b>
            <small>estimate</small>
          </>
        )}
      </div>

      <div className={`tile rider-tile colour-swap ${o.rider && !ended ? "lemon" : ""}`} key={`rider-${o.rider?.id ?? "none"}`}>
        {o.rider && !ended ? (
          <>
            <span className="av" aria-hidden="true">{o.rider.name[0]}</span>
            <div style={{ minWidth: 0 }}>
              <b>{o.rider.name}</b>
              <small>{o.rider.vehicle}</small>
            </div>
            <button className="chip white" style={{ marginLeft: "auto" }} onClick={() => toast(`Call ${o.rider!.name.split(" ")[0]}`, `Numbers are masked (${o.rider!.phone_masked}). Calls are simulated in this demo.`, "ok")}>
              ☎ Call
            </button>
          </>
        ) : findingRider ? (
          <>
            <span className="av" aria-hidden="true">📡</span>
            <div><b>Finding a rider…</b><small>the nearest free rider takes it</small></div>
          </>
        ) : (
          <>
            <span className="av" aria-hidden="true">🛵</span>
            <div><b>{ended ? "No rider" : "Rider"}</b><small>{ended ? "—" : "assigned when the kitchen accepts"}</small></div>
          </>
        )}
      </div>

      <div className={`tile rail-tile colour-swap ${delivered ? "mint" : ""}`}>
        <p className="rail-now" aria-live="polite">
          {STATUS_LABEL[status]}
          {o.timestamps[status] ? `, ${clock(o.timestamps[status]!)}` : ""}
        </p>
        <ol className="rail" aria-label="Order progress">
          {STEPS.map((s, i) => {
            const at = o.timestamps[s.status];
            const state = ended ? (at ? "on" : "") : i < curIndex || delivered ? "on" : i === curIndex ? "cur" : "";
            return (
              <li key={s.status} className={`step ${state}`} aria-current={state === "cur" ? "step" : undefined}>
                <i className={s.status === "preparing" && status === "preparing" ? "steam" : undefined} aria-hidden="true">{s.icon}</i>
                {s.label}
                <small className="num">{at ? clock(at) : ""}</small>
              </li>
            );
          })}
        </ol>
      </div>

      <section className="tile totals summary" aria-labelledby="sum-h">
        <div className="row" style={{ marginBottom: 6 }}>
          {o.restaurant.cover && <Image src={o.restaurant.cover.url} alt="" width={48} height={36} style={{ width: 48, height: 36, borderRadius: 10, objectFit: "cover" }} />}
          <h2 id="sum-h" style={{ fontSize: 15 }}>
            <Link href={`/r/${o.restaurant.slug}`}>{o.restaurant.name}</Link>
          </h2>
        </div>
        {o.items.map((i) => (
          <div key={i.name}>
            <span><span className={`veg ${i.is_veg ? "" : "non"}`} aria-hidden="true" /> {i.qty} × {i.name}</span>
            <span className="num">{inr(i.qty * i.price_paise)}</span>
          </div>
        ))}
        <div><span>Delivery · {km(o.totals.distance_m)}</span><span className="num">{inr(o.totals.delivery_fee_paise)}</span></div>
        <div><span>Platform fee</span><span className="num">{inr(o.totals.platform_fee_paise)}</span></div>
        <div className="t"><span>{o.payment === "cod" ? "Cash on delivery" : "Paid"}</span><span className="num">{inr(o.totals.total_paise)}</span></div>
        {o.note && <p className="chip lemon" style={{ marginTop: 8, whiteSpace: "normal" }}>“{o.note}”</p>}
        {(delivered || ended) && (
          <div className="row" style={{ marginTop: 10 }}>
            <Link className="btn small" href={`/r/${o.restaurant.slug}`}>Order again</Link>
            <Link className="btn small ghost" href="/orders">All orders</Link>
          </div>
        )}
      </section>
    </main>
  );
}
