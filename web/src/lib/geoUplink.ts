// The rider phone's GPS uplink (R7, 04 §3): watchPosition → POST /rider/position, throttled to one
// fix every 3 s or every 5 m moved (whichever comes first, never more than once a second), with a
// screen wake lock so the phone doesn't sleep mid-delivery.
//
// Relay mode: a reviewer outside Bengaluru can still run the two-phone demo. If the first fix is
// more than 30 km from the seeded area, every fix is replayed as an offset from an anchor in
// Koramangala (the current job's restaurant, or Koramangala 5th Block) — their real steps, moved.
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { AREA_CENTRE, bearing, haversine, type LatLng } from "./geo";

export type UplinkStatus = "off" | "asking" | "on" | "denied" | "unavailable" | "error";
export type UplinkFix = { lat: number; lng: number; heading: number | null; speed: number | null; at: number };
export type Uplink = { status: UplinkStatus; last: UplinkFix | null; sent: number; relay: boolean; error?: string };

const MIN_GAP_MS = 1000;
const MAX_GAP_MS = 3000;
const MIN_MOVE_M = 5;
const RELAY_KM = 30;
const KORAMANGALA_5TH: LatLng = [12.9349, 77.62];
const STORAGE_KEY = "platter.share.v1";

const rad = (d: number) => (d * Math.PI) / 180;

type Relay = { origin: LatLng; anchor: LatLng } | null;

/** Watches GPS while `enabled`; `anchor` is where relay mode replays the phone's movement. */
export function useGeoUplink(enabled: boolean, anchor: LatLng | null): Uplink {
  const [state, setState] = useState<Uplink>({ status: "off", last: null, sent: 0, relay: false });
  const anchorRef = useRef(anchor);
  anchorRef.current = anchor;

  useEffect(() => {
    if (!enabled) {
      setState((s) => ({ ...s, status: "off", last: null, relay: false, error: undefined }));
      return;
    }
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setState((s) => ({ ...s, status: "unavailable", error: undefined }));
      return;
    }

    let cancelled = false;
    let relay: Relay | undefined; // undefined = not decided yet (no fix so far)
    let prev: LatLng | null = null;
    let prevHeading: number | null = null;
    let latest: UplinkFix | null = null;
    let lastSentAt = 0;
    let lastSentPos: LatLng | null = null;
    let inFlight = false;
    let lock: WakeLockSentinel | null = null;

    setState((s) => ({ ...s, status: "asking", error: undefined }));

    const send = async (fix: UplinkFix) => {
      if (inFlight) return;
      inFlight = true;
      lastSentAt = Date.now();
      lastSentPos = [fix.lat, fix.lng];
      try {
        await api<void>("/rider/position", {
          body: {
            lat: fix.lat,
            lng: fix.lng,
            ...(fix.heading !== null ? { heading: fix.heading } : {}),
            ...(fix.speed !== null ? { speed_mps: fix.speed } : {}),
            at: new Date(fix.at).toISOString(),
          },
        });
        if (!cancelled) setState((s) => ({ ...s, sent: s.sent + 1, error: undefined }));
      } catch {
        // one dropped fix is harmless — the next one supersedes it
      } finally {
        inFlight = false;
      }
    };

    const maybeSend = (fix: UplinkFix) => {
      const gap = Date.now() - lastSentAt;
      if (gap < MIN_GAP_MS) return;
      const moved = lastSentPos ? haversine(lastSentPos, [fix.lat, fix.lng]) : Infinity;
      if (gap >= MAX_GAP_MS || moved >= MIN_MOVE_M) void send(fix);
    };

    const onFix = (p: GeolocationPosition) => {
      if (cancelled) return;
      const raw: LatLng = [p.coords.latitude, p.coords.longitude];
      if (relay === undefined) {
        relay =
          haversine(raw, AREA_CENTRE) > RELAY_KM * 1000
            ? { origin: raw, anchor: anchorRef.current ?? KORAMANGALA_5TH }
            : null;
      }
      let pos = raw;
      if (relay) {
        // keep metres, not degrees: a longitude degree is shorter the further from the equator
        const k = Math.cos(rad(relay.origin[0])) / Math.cos(rad(relay.anchor[0]));
        pos = [relay.anchor[0] + (raw[0] - relay.origin[0]), relay.anchor[1] + (raw[1] - relay.origin[1]) * k];
      }
      const h = p.coords.heading;
      let heading: number | null = h !== null && !Number.isNaN(h) ? h : null;
      if (heading === null && prev && haversine(prev, pos) >= 2) heading = bearing(prev, pos);
      if (heading === null) heading = prevHeading;
      const speed = p.coords.speed !== null && !Number.isNaN(p.coords.speed) ? p.coords.speed : null;
      prev = pos;
      prevHeading = heading;
      latest = { lat: pos[0], lng: pos[1], heading, speed, at: p.timestamp || Date.now() };
      setState((s) => ({ ...s, status: "on", last: latest, relay: relay !== null, error: undefined }));
      maybeSend(latest);
    };

    const onError = (e: GeolocationPositionError) => {
      if (cancelled) return;
      if (e.code === e.PERMISSION_DENIED) setState((s) => ({ ...s, status: "denied", error: undefined }));
      else
        setState((s) => ({
          ...s,
          status: "error",
          error: e.code === e.TIMEOUT ? "No GPS signal yet. Try near a window or outdoors" : "GPS is unavailable right now",
        }));
    };

    const watch = navigator.geolocation.watchPosition(onFix, onError, {
      enableHighAccuracy: true,
      maximumAge: 0,
      timeout: 15_000,
    });

    // A standing phone may not report new fixes; still tell dispatch "here" every 3 s while the
    // last real fix is fresh (< 30 s).
    const heartbeat = window.setInterval(() => {
      if (latest && Date.now() - latest.at < 30_000 && Date.now() - lastSentAt >= MAX_GAP_MS) {
        void send({ ...latest, at: Date.now() });
      }
    }, 1000);

    const acquire = async () => {
      try {
        if ("wakeLock" in navigator && document.visibilityState === "visible" && !lock) {
          lock = await navigator.wakeLock.request("screen");
          lock.addEventListener("release", () => {
            lock = null;
          });
          if (cancelled) void lock.release();
        }
      } catch {
        // low battery or not allowed — sharing still works, the screen may just sleep
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") void acquire();
    };
    void acquire();
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      navigator.geolocation.clearWatch(watch);
      window.clearInterval(heartbeat);
      document.removeEventListener("visibilitychange", onVisible);
      if (lock) void lock.release().catch(() => undefined);
    };
  }, [enabled]);

  return state;
}

/** The "Share my location" toggle, remembered across reloads (re-asks permission on load). */
export function useShareToggle(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(false);
  useEffect(() => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY) === "1") setOn(true);
    } catch {
      // storage blocked — the toggle just starts off
    }
  }, []);
  const set = useCallback((next: boolean) => {
    setOn(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // ignore
    }
  }, []);
  return [on, set];
}
