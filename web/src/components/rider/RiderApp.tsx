"use client";

// S8 — the rider's phone (R7). A dark map tile with the current leg, the job tile (pickup → drop),
// the "Share my location" switch that drives the GPS uplink, and two huge buttons. Everything
// refreshes from /rider/me whenever the rider stream says something changed.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Map, type MapMarker, type MapRoute } from "@/components/map/Map";
import { RoleBar } from "@/components/ui/RoleBar";
import { api, ApiError, errorMessage, type Job, type RiderMe } from "@/lib/api";
import { etaLabel, inr, km } from "@/lib/format";
import { AREA_CENTRE, haversine, type LatLng } from "@/lib/geo";
import { useGeoUplink, useShareToggle, type Uplink } from "@/lib/geoUplink";
import { useEventStream } from "@/lib/stream";
import { toast } from "@/lib/toast";
import "./rider.css";

type Step = "picked_up" | "delivered";

export function RiderApp() {
  const [me, setMe] = useState<RiderMe | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Step | null>(null);
  const [share, setShare] = useShareToggle();
  const job = me?.job ?? null;
  const anchor = useMemo<LatLng | null>(
    () => (job ? [job.restaurant.lat, job.restaurant.lng] : null),
    [job],
  );
  const uplink = useGeoUplink(share, anchor);

  const load = useCallback(async () => {
    try {
      const data = await api<RiderMe>("/rider/me");
      setMe(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // the app shell works offline-ish once installed; /api and the stream are never cached
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => undefined);
    }
  }, []);

  const debounce = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(debounce.current), []);
  const stream = useEventStream("/api/rider/events", (name) => {
    if (name === "ping" || name === "ready") return;
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => void load(), 250);
  });

  const transition = async (to: Step) => {
    if (!job || busy) return;
    setBusy(to);
    try {
      const next = await api<Job | null>(`/rider/orders/${job.order_id}/transition`, { body: { to } });
      setMe((m) => (m ? { ...m, job: next ?? null } : m));
      if (to === "delivered") {
        toast("Delivered 🎉", next ? `Next up: ${next.restaurant.name}` : "Nice ride — that's one more for today.", "ok");
      }
      void load();
    } catch (err) {
      toast(errorMessage(err));
      if (err instanceof ApiError && err.status === 409) void load();
    } finally {
      setBusy(null);
    }
  };

  const live = stream.connected && !stream.stale;

  return (
    <main id="main" className="rd">
      <RoleBar
        title={me?.rider.name ?? "Rider"}
        subtitle={me ? me.rider.vehicle : undefined}
        who="🛵 Rider"
        dark
      >
        <span className={`chip ${live ? "live" : "peach"}`} role="status">
          {live ? "Live" : "Reconnecting…"}
        </span>
      </RoleBar>

      {!me && !loadError && <Skeletons />}
      {!me && loadError && (
        <section className="tile peach rd-wide" role="alert">
          <h2>Couldn&apos;t load your shift</h2>
          <p style={{ marginTop: 6 }}>{loadError}</p>
          <button className="btn rd-touch" style={{ marginTop: 12 }} onClick={() => void load()}>
            Retry
          </button>
        </section>
      )}

      {me && (
        <>
          <MapTile job={job} uplink={uplink} />
          {job ? <JobTile job={job} /> : <IdleTiles me={me} />}
          <ShareTile on={share} onChange={setShare} uplink={uplink} />
          {job && <Actions job={job} busy={busy} onStep={transition} />}
        </>
      )}
    </main>
  );
}

function Skeletons() {
  return (
    <>
      <div className="skeleton rd-wide rd-map" aria-hidden="true" />
      <div className="skeleton rd-wide" style={{ height: 110 }} aria-hidden="true" />
      <div className="skeleton rd-wide" style={{ height: 70 }} aria-hidden="true" />
      <p className="sr-only" role="status">
        Loading your shift…
      </p>
    </>
  );
}

// ── map ──────────────────────────────────────────────────────────────────────────────────────

function MapTile({ job, uplink }: { job: Job | null; uplink: Uplink }) {
  const self = uplink.status === "on" || uplink.status === "error" ? uplink.last : null;
  const now = useNow(1000);

  const markers = useMemo<MapMarker[]>(() => {
    const out: MapMarker[] = [];
    if (job) {
      out.push({ id: "rest", kind: "restaurant", lat: job.restaurant.lat, lng: job.restaurant.lng, title: job.restaurant.name });
      out.push({ id: "drop", kind: "drop", lat: job.drop.lat, lng: job.drop.lng, title: `Drop · ${job.drop.line}` });
    }
    if (self) out.push({ id: "me", kind: "rider", lat: self.lat, lng: self.lng, heading: self.heading, color: "#FF7A59", title: "You" });
    return out;
  }, [job, self]);

  const routes = useMemo<MapRoute[]>(
    () => (job?.leg ? [{ id: `${job.order_id}-${job.leg.kind}`, polyline: job.leg.polyline, color: "#FFF1B8" }] : []),
    [job],
  );

  const fit = useMemo<LatLng[]>(() => {
    const pts: LatLng[] = [];
    if (job) pts.push([job.restaurant.lat, job.restaurant.lng], [job.drop.lat, job.drop.lng]);
    if (self) pts.push([self.lat, self.lng]);
    return pts;
  }, [job, self]);
  // refit when the job (or its phase) changes, and once when the first GPS fix arrives
  const fitKey = `${job?.order_id ?? "idle"}:${job?.phase ?? ""}:${self ? "me" : ""}`;

  const gpsAge = self ? Math.max(0, Math.round((now - self.at) / 1000)) : null;
  const kmh = self?.speed != null ? Math.round(self.speed * 3.6) : null;

  return (
    <section className="tile flush rd-wide rd-map">
      <Map label="Your delivery map" dark center={AREA_CENTRE} zoom={14} markers={markers} routes={routes} fit={fit} fitKey={fitKey}>
        <div className="rd-hud">
          {kmh !== null && <span className="num">{kmh} km/h</span>}
          <span className="num">{gpsAge !== null ? `GPS ● ${gpsAge} s` : "GPS off"}</span>
          {job && <span className="num">{inr(job.pay_preview_paise)}</span>}
        </div>
      </Map>
    </section>
  );
}

function useNow(every: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), every);
    return () => window.clearInterval(t);
  }, [every]);
  return now;
}

// ── job / idle ───────────────────────────────────────────────────────────────────────────────

function JobTile({ job }: { job: Job }) {
  const items = `${job.items_count} item${job.items_count === 1 ? "" : "s"}`;
  const dropKm = km(haversine([job.restaurant.lat, job.restaurant.lng], [job.drop.lat, job.drop.lng]));
  const ride = job.leg ? ` · ${etaLabel(job.leg.duration_s, job.leg.method)} ride` : "";
  const ready = job.status === "ready";

  if (job.phase === "to_customer") {
    return (
      <section className="tile lemon rd-wide rd-job spring" key={`${job.order_id}-drop`} aria-live="polite">
        <small>
          Drop · {job.number} · {job.payment === "cod" ? `COD ${inr(job.total_paise)}` : "Paid"}
        </small>
        <b>{job.drop.line}</b>
        <p>
          For {job.customer_first_name} · {items}
          {ride}
        </p>
        {job.note && <p className="rd-note">📝 {job.note}</p>}
        <ItemList job={job} />
      </section>
    );
  }

  const heading =
    job.phase === "waiting" ? "At the counter — waiting for the kitchen" : `Pickup · ${job.number} · then ${dropKm} to the drop`;
  return (
    <section className="tile sky rd-wide rd-job spring" key={`${job.order_id}-pickup`} aria-live="polite">
      <small>{heading}</small>
      <b>{job.restaurant.name}</b>
      <p>
        {job.restaurant.line} · {items} · {ready ? "ready — go!" : "kitchen is cooking"}
        {job.phase === "to_restaurant" ? ride : ""} · you earn {inr(job.pay_preview_paise)}
      </p>
      <ItemList job={job} />
    </section>
  );
}

function ItemList({ job }: { job: Job }) {
  if (job.items.length === 0) return null;
  return (
    <details className="rd-items">
      <summary>What&apos;s in the bag</summary>
      <ul>
        {job.items.map((it, i) => (
          <li key={`${it.name}-${i}`}>
            <span role="img" className={`veg ${it.is_veg ? "" : "non"}`} aria-label={it.is_veg ? "Veg" : "Non-veg"} />
            <span className="num">{it.qty} ×</span> {it.name}
          </li>
        ))}
      </ul>
    </details>
  );
}

function IdleTiles({ me }: { me: RiderMe }) {
  return (
    <>
      <section className="tile lav rd-wide rd-job spring">
        <small>Waiting for work</small>
        <b>No job right now</b>
        <p>Jobs arrive when a restaurant accepts an order near you. Keep sharing your location so dispatch can find you.</p>
      </section>
      <section className="tile mint rd-stat spring">
        <span className="label">Today</span>
        <b className="num">{me.today.deliveries}</b>
        <span>deliver{me.today.deliveries === 1 ? "y" : "ies"}</span>
      </section>
      <section className="tile peach rd-stat spring">
        <span className="label">Earned today</span>
        <b className="num">{inr(me.today.pay_paise)}</b>
        <span>paid per drop</span>
      </section>
    </>
  );
}

// ── share toggle ─────────────────────────────────────────────────────────────────────────────

function ShareTile({ on, onChange, uplink }: { on: boolean; onChange: (on: boolean) => void; uplink: Uplink }) {
  const text: Record<Uplink["status"], string> = {
    off: "Off — switch it on and the customer watches you ride. Dispatch only sends new jobs to riders sharing their location.",
    asking: "Asking your phone for GPS… allow location when it asks.",
    on: `On · sent ${uplink.sent} fix${uplink.sent === 1 ? "" : "es"}`,
    denied:
      "Location is blocked for this site. Tap the 🔒 next to the address, allow Location, then switch this off and on again.",
    unavailable: "This browser can't share GPS — try Chrome or Safari on a phone.",
    error: uplink.error ?? "GPS hiccup — still trying…",
  };
  return (
    <section className="tile rd-wide rd-share">
      <div className="between">
        <span id="share-label" className="rd-share-title">
          📡 Share my location
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-labelledby="share-label"
          className="switch rd-switch"
          onClick={() => onChange(!on)}
        />
      </div>
      <p className={uplink.status === "denied" || uplink.status === "error" ? "error-text" : "muted"} role="status">
        {text[uplink.status]}
      </p>
      {uplink.relay && uplink.status === "on" && (
        <span className="chip lemon" title="Your phone is far from Bengaluru, so its movement is replayed in Koramangala">
          Relay: your steps, moved to Koramangala
        </span>
      )}
    </section>
  );
}

// ── the two big buttons ──────────────────────────────────────────────────────────────────────

function Actions({ job, busy, onStep }: { job: Job; busy: Step | null; onStep: (s: Step) => void }) {
  const canPick = job.status === "ready";
  const canDrop = job.status === "picked_up";
  const pickWhy = canPick ? "Food is ready" : job.status === "picked_up" ? "Already picked up ✓" : "Kitchen is still cooking";
  const dropWhy = canDrop ? `Hand it to ${job.customer_first_name}` : "After pickup";
  return (
    <>
      <button
        type="button"
        className={`tile rd-big ${canPick ? "go respring" : "off"}`}
        disabled={!canPick || busy !== null}
        onClick={() => onStep("picked_up")}
        aria-describedby="pick-why"
      >
        <span>{busy === "picked_up" ? "Saving…" : "Picked up"}</span>
        <small id="pick-why">{pickWhy}</small>
      </button>
      <button
        type="button"
        className={`tile rd-big ${canDrop ? "go respring" : "off"}`}
        disabled={!canDrop || busy !== null}
        onClick={() => onStep("delivered")}
        aria-describedby="drop-why"
      >
        <span>{busy === "delivered" ? "Saving…" : "Delivered 🎉"}</span>
        <small id="drop-why">{dropWhy}</small>
      </button>
    </>
  );
}
