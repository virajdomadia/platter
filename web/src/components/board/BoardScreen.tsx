"use client";

// S7 — the kitchen board (R8). Four columns of KOT tickets fed by GET /restaurant/board and kept
// fresh by the restaurant SSE stream: status / rider-assignment frames refetch (debounced), rider
// fixes patch the ticket's distance + ETA in place. New orders "print" into the New column.
import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { PushOptIn } from "@/components/ui/PushOptIn";
import { RoleBar } from "@/components/ui/RoleBar";
import { api, errorMessage, type Board, type Ticket as TicketT } from "@/lib/api";
import { age, inr } from "@/lib/format";
import { useEventStream } from "@/lib/stream";
import { toast } from "@/lib/toast";
import { BoardTabs } from "./BoardTabs";
import { useChime } from "./chime";
import { Ticket, type TransitionTo } from "./Ticket";
import "./board.css";

type ColKey = "new" | "cooking" | "ready" | "out";
type Loaded = { board: Board; at: number }; // `at`: client time the board's age_s values were true
type RiderFrame = { order_id: string; distance_m: number | null; eta_s: number | null };

const COLS: { key: ColKey; title: string; emoji: string; tone: string; empty: string }[] = [
  { key: "new", title: "New", emoji: "🧾", tone: "peach", empty: "No new orders. The next one prints here." },
  { key: "cooking", title: "Cooking", emoji: "🍳", tone: "lemon", empty: "Nothing on the stove right now." },
  { key: "ready", title: "Ready", emoji: "🛍️", tone: "mint", empty: "Nothing waiting at the counter." },
  { key: "out", title: "Out for delivery", emoji: "🛵", tone: "sky", empty: "No one on the road yet." },
];

const BASE_TITLE = "Kitchen board · Platter";
const FRESH_MS = 6000;
const STREAM_URL = "/api/restaurant/events";

function columnOf(status: TicketT["status"]): ColKey | null {
  switch (status) {
    case "placed":
      return "new";
    case "accepted":
    case "preparing":
      return "cooking";
    case "ready":
      return "ready";
    case "picked_up":
      return "out";
    default:
      return null;
  }
}

function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function withViewTransition(update: () => void): void {
  const doc = document as unknown as { startViewTransition?: (cb: () => void) => unknown };
  if (typeof doc.startViewTransition !== "function" || reducedMotion()) {
    update();
    return;
  }
  doc.startViewTransition.call(document, () => flushSync(update));
}

/** Moves `t` into the column its status belongs to (or drops it if it left the board). */
function placeTicket(d: Loaded, t: TicketT): Loaded {
  const board: Board = { ...d.board };
  for (const c of COLS) board[c.key] = board[c.key].filter((x) => x.id !== t.id);
  const col = columnOf(t.status);
  if (col) {
    // keep every age_s relative to the same `at`
    const adjusted = { ...t, age_s: t.age_s - (Date.now() - d.at) / 1000 };
    board[col] = [...board[col], adjusted];
  }
  return { ...d, board };
}

function patchRider(d: Loaded, f: RiderFrame): Loaded {
  let changed = false;
  const board: Board = { ...d.board };
  for (const c of COLS) {
    board[c.key] = board[c.key].map((t) => {
      if (t.id !== f.order_id || !t.rider) return t;
      if (t.rider.distance_m === f.distance_m && t.rider.eta_s === f.eta_s) return t;
      changed = true;
      return { ...t, rider: { ...t.rider, distance_m: f.distance_m, eta_s: f.eta_s } };
    });
  }
  return changed ? { ...d, board } : d;
}

function sorted(list: TicketT[], newestFirst: boolean): TicketT[] {
  return [...list].sort((a, b) => {
    const diff = Date.parse(a.placed_at) - Date.parse(b.placed_at);
    return newestFirst ? -diff : diff;
  });
}

export function BoardScreen() {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set());
  const [prints, setPrints] = useState(0);
  const [announce, setAnnounce] = useState("");
  const [recon, setRecon] = useState(false);

  const dataRef = useRef<Loaded | null>(null);
  dataRef.current = data;
  const seen = useRef<Set<string> | null>(null); // null until the first load: nothing prints on page open
  const reqId = useRef(0);
  const refetchTimer = useRef<number | undefined>(undefined);
  const freshTimers = useRef<number[]>([]);
  const chime = useChime();
  const playChime = chime.play;

  const printed = useCallback(
    (tickets: TicketT[]) => {
      const ids = tickets.map((t) => t.id);
      setFresh((s) => new Set([...s, ...ids]));
      setPrints((n) => n + 1);
      setAnnounce(tickets.map((t) => `New order ${t.number}`).join(". "));
      playChime();
      freshTimers.current.push(
        window.setTimeout(() => {
          setFresh((s) => {
            const next = new Set(s);
            ids.forEach((id) => next.delete(id));
            return next;
          });
        }, FRESH_MS),
      );
    },
    [playChime],
  );

  const load = useCallback(async () => {
    const id = ++reqId.current;
    try {
      const board = await api<Board>("/restaurant/board");
      if (id !== reqId.current) return;
      const known = seen.current;
      const arrivals = known ? board.new.filter((t) => !known.has(t.id)) : [];
      const next = new Set(known ?? []);
      for (const c of COLS) board[c.key].forEach((t) => next.add(t.id));
      seen.current = next;
      setError(null);
      setData({ board, at: Date.now() });
      if (arrivals.length) printed(arrivals);
    } catch (err) {
      if (id !== reqId.current) return;
      if (dataRef.current) toast("Couldn't refresh the board", errorMessage(err));
      else setError(errorMessage(err));
    }
  }, [printed]);

  const refetchSoon = useCallback(() => {
    window.clearTimeout(refetchTimer.current);
    refetchTimer.current = window.setTimeout(() => void load(), 250);
  }, [load]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    const timers = freshTimers.current;
    return () => {
      window.clearInterval(tick);
      window.clearTimeout(refetchTimer.current);
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, []);

  const stream = useEventStream(STREAM_URL, (name, raw) => {
    if (name === "status" || name === "rider_assigned" || name === "rider_reassigned") {
      refetchSoon();
    } else if (name === "ready") {
      // (re)connected: catch up if anything moved while we were away
      const seq = (raw as { seq?: number } | null)?.seq;
      if (dataRef.current && seq !== dataRef.current.board.seq) refetchSoon();
    } else if (name === "rider" && raw) {
      const f = raw as RiderFrame;
      setData((d) => (d ? patchRider(d, f) : d));
    }
  });

  const healthy = stream.connected && !stream.stale;
  useEffect(() => {
    if (healthy) {
      setRecon(false);
      return;
    }
    const t = window.setTimeout(() => setRecon(true), 4000);
    return () => window.clearTimeout(t);
  }, [healthy]);

  const newCount = data?.board.new.length ?? 0;
  useEffect(() => {
    document.title = newCount > 0 ? `(${newCount}) New order · Platter` : BASE_TITLE;
  }, [newCount]);
  useEffect(
    () => () => {
      document.title = BASE_TITLE;
    },
    [],
  );

  const transition = useCallback(
    async (id: string, to: TransitionTo, reason?: string) => {
      try {
        const t = await api<TicketT>(`/restaurant/orders/${id}/transition`, {
          method: "POST",
          body: reason ? { to, reason } : { to },
        });
        const apply = () => setData((d) => (d ? placeTicket(d, t) : d));
        if (to === "accepted") withViewTransition(apply);
        else apply();
        if (to === "rejected") toast(`${t.number} rejected`, "The customer has been told why.", "ok");
      } catch (err) {
        toast(errorMessage(err));
        refetchSoon();
      }
    },
    [refetchSoon],
  );

  const r = data?.board.restaurant;
  const today = data?.board.today;
  const anyPreparing = data?.board.cooking.some((t) => t.status === "preparing") ?? false;

  return (
    <>
      <RoleBar
        title={r ? r.name : "Kitchen"}
        subtitle={r ? `${r.area} · ${r.is_open ? (r.hours_label === "Open 24 hours" ? "Open 24 hours" : `Open · ${r.hours_label}`) : `Closed · ${r.hours_label}`}` : undefined}
        who="🍳 Kitchen"
      >
        <BoardTabs current="board" />
        {healthy ? (
          <span className="chip live mint">Live</span>
        ) : recon ? (
          <span className="chip lemon">Reconnecting…</span>
        ) : null}
        <button
          type="button"
          className="chip lav bd-chip-btn"
          aria-pressed={chime.on}
          onClick={chime.toggle}
          title="Chime when a new order lands"
        >
          {chime.on ? "🔔 Sound on" : "🔕 Sound off"}
        </button>
      </RoleBar>

      {!chime.on && (
        <div className="tile lemon bd-sound" role="note">
          <span>Sound is off: a new order prints silently.</span>
          <button type="button" className="btn small" onClick={chime.toggle}>
            Turn on sound
          </button>
        </div>
      )}

      <PushOptIn className="sky">Get a notification for every new order, even with this tab closed.</PushOptIn>

      <p className="sr-only" aria-live="polite" role="status">
        {announce}
      </p>

      {error && !data && (
        <div className="tile peach spring" role="alert" style={{ marginTop: 10 }}>
          <h2>Couldn&apos;t load the board</h2>
          <p className="muted" style={{ margin: "4px 0 12px" }}>
            {error}
          </p>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setError(null);
              void load();
            }}
          >
            Retry
          </button>
        </div>
      )}

      {!error && !data && (
        <div aria-busy="true" aria-label="Loading the board">
          <div className="bd-stats">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton" style={{ height: 76 }} />
            ))}
          </div>
          <div className="bd-cols">
            {COLS.map((c) => (
              <div key={c.key} className="skeleton" style={{ height: 360 }} />
            ))}
          </div>
        </div>
      )}

      {data && today && (
        <>
          <section className="bd-stats" aria-label="Today">
            <div className="tile spring bd-stat">
              <span className="label">Orders today</span>
              <b className="num">{today.orders}</b>
            </div>
            <div className="tile spring bd-stat">
              <span className="label">Revenue</span>
              <b className="num">{inr(today.revenue_paise)}</b>
            </div>
            <div className="tile spring bd-stat">
              <span className="label">Avg accept</span>
              <b className="num">{today.avg_accept_s != null ? age(today.avg_accept_s) : "—"}</b>
            </div>
          </section>

          <div className="bd-cols">
            {COLS.map((c) => {
              const list = sorted(data.board[c.key], c.key === "new");
              return (
                <section key={c.key} className={`tile ${c.tone} bd-col spring`} aria-labelledby={`col-${c.key}`}>
                  {c.key === "new" && prints > 0 && <span key={prints} className="bd-pulse" aria-hidden="true" />}
                  <h2 id={`col-${c.key}`}>
                    <span className={c.key === "cooking" && anyPreparing ? "steam" : undefined} aria-hidden="true">
                      {c.emoji}
                    </span>
                    {c.title}
                    <span className="n num">
                      {list.length}
                      <span className="sr-only"> orders</span>
                    </span>
                  </h2>
                  {list.length === 0 ? (
                    <p className="bd-empty">{c.empty}</p>
                  ) : (
                    <ul className="bd-list">
                      {list.map((t) => (
                        <li key={t.id} className={c.key === "new" && fresh.has(t.id) ? "bd-slot" : undefined}>
                          <Ticket
                            ticket={t}
                            ageS={t.age_s + (now - data.at) / 1000}
                            fresh={c.key === "new" && fresh.has(t.id)}
                            onTransition={transition}
                          />
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}
