// SSE consumers (04 §8). One EventSource per screen; the browser resends `Last-Event-ID` on every
// reconnect and the API replays exactly what was missed from `order_events`, so there is nothing
// to do on `reconnect` but let it happen. A banner appears if no frame (not even `ping`) arrives for
// 45 s. A hidden tab closes its stream (each one keeps a server function busy) and reopens it with
// `?since=` the last id when shown again, so nothing is missed.
"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import type { EtaOut, OrderOut, RiderFix, RouteOut, StatusEvent } from "./api";

export const EVENTS = [
  "snapshot",
  "ready",
  "status",
  "rider_assigned",
  "rider_reassigned",
  "route",
  "rider",
  "riders",
  "eta",
  "ping",
  "reconnect",
] as const;
export type EventName = (typeof EVENTS)[number];

export type StreamState = { connected: boolean; stale: boolean; lastFrameAt: number };

/** Opens `url` and calls `onEvent(name, data)` for every frame. */
export function useEventStream(
  url: string | null,
  onEvent: (name: EventName, data: unknown) => void,
): StreamState {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const [state, setState] = useState<StreamState>({ connected: false, stale: false, lastFrameAt: 0 });
  const [visible, setVisible] = useState(true);
  const lastId = useRef<{ url: string; id: string } | null>(null);

  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  useEffect(() => {
    if (!url || !visible) return;
    const since = lastId.current?.url === url ? lastId.current.id : null;
    const es = new EventSource(since ? `${url}${url.includes("?") ? "&" : "?"}since=${encodeURIComponent(since)}` : url, {
      withCredentials: true,
    });
    let last = Date.now();
    const seen = () => {
      last = Date.now();
      setState((s) => (s.connected && !s.stale ? s : { connected: true, stale: false, lastFrameAt: last }));
    };
    const listeners = EVENTS.map((name) => {
      const fn = (e: MessageEvent) => {
        seen();
        if (e.lastEventId) lastId.current = { url, id: e.lastEventId };
        try {
          handler.current(name, e.data ? JSON.parse(e.data) : null);
        } catch {
          /* a malformed frame is skipped, never fatal */
        }
      };
      es.addEventListener(name, fn as EventListener);
      return [name, fn] as const;
    });
    es.onopen = seen;
    es.onerror = () => setState((s) => ({ ...s, connected: false }));
    const watchdog = window.setInterval(() => {
      if (Date.now() - last > 45_000) setState((s) => ({ ...s, stale: true }));
    }, 5_000);
    return () => {
      window.clearInterval(watchdog);
      listeners.forEach(([name, fn]) => es.removeEventListener(name, fn as EventListener));
      es.close();
    };
  }, [url, visible]);

  return state;
}

// --- the tracking page -------------------------------------------------------------------------

export type Live = {
  order: OrderOut;
  fix: RiderFix | null;
  fixAt: number; // client time the last rider fix arrived (for "signal weak")
  eta: EtaOut | null;
  justChanged: string | null;
};

type Action =
  | { type: "snapshot"; order: OrderOut }
  | { type: "status"; data: StatusEvent }
  | { type: "rider_assigned"; data: { rider: OrderOut["rider"] } }
  | { type: "route"; data: RouteOut }
  | { type: "rider"; data: RiderFix }
  | { type: "eta"; data: EtaOut };

const ACTIVE = new Set(["placed", "accepted", "preparing", "ready", "picked_up"]);

export function liveReducer(state: Live, action: Action): Live {
  switch (action.type) {
    case "snapshot":
      return {
        order: action.order,
        fix: action.order.rider_position ?? state.fix,
        fixAt: action.order.rider_position ? Date.now() : state.fixAt,
        eta: action.order.eta ?? null,
        justChanged: null,
      };
    case "status": {
      const d = action.data;
      if (state.order.events.some((e) => e.status === d.status)) return state;
      const order: OrderOut = {
        ...state.order,
        status: d.status,
        reject_reason: d.reason ?? state.order.reject_reason,
        events: [...state.order.events, d],
        timestamps: { ...state.order.timestamps, [d.status]: d.at },
      };
      return {
        ...state,
        order,
        eta: ACTIVE.has(d.status) ? state.eta : null,
        fix: ACTIVE.has(d.status) ? state.fix : null,
        justChanged: d.status,
      };
    }
    case "rider_assigned":
      return { ...state, order: { ...state.order, rider: action.data.rider }, justChanged: "rider" };
    case "route": {
      const leg = action.data;
      const legs = [...state.order.legs.filter((l) => l.kind !== leg.kind), leg];
      return { ...state, order: { ...state.order, legs } };
    }
    case "rider":
      return { ...state, fix: action.data, fixAt: Date.now() };
    case "eta":
      return { ...state, eta: action.data };
  }
}

export function useOrderStream(initial: OrderOut) {
  const [live, dispatch] = useReducer(liveReducer, initial, (order) =>
    liveReducer({ order, fix: null, fixAt: 0, eta: null, justChanged: null }, { type: "snapshot", order }),
  );
  const done = !ACTIVE.has(live.order.status);
  const stream = useEventStream(done ? null : `/api/orders/${initial.id}/events`, (name, data) => {
    if (name === "snapshot") dispatch({ type: "snapshot", order: data as OrderOut });
    else if (name === "status") dispatch({ type: "status", data: data as StatusEvent });
    else if (name === "rider_assigned" || name === "rider_reassigned")
      dispatch({ type: "rider_assigned", data: data as { rider: OrderOut["rider"] } });
    else if (name === "route") dispatch({ type: "route", data: data as RouteOut });
    else if (name === "rider") dispatch({ type: "rider", data: data as RiderFix });
    else if (name === "eta") dispatch({ type: "eta", data: data as EtaOut });
  });
  return { live, stream };
}
