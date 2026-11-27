"use client";

// One KOT ticket on the kitchen board: number + live age, who/how paid/total, the items, the note,
// the rider line and the one action that moves it along.
import { useState } from "react";
import type { CSSProperties } from "react";
import type { Ticket as TicketT } from "@/lib/api";
import { age, inr, km, minutes } from "@/lib/format";

export type TransitionTo = "accepted" | "rejected" | "preparing" | "ready";

const REASONS = ["Out of an item", "Kitchen too busy", "Closing soon"] as const;
const LATE_S = 180;
// shortcut: one cooking threshold for every kitchen (the ticket doesn't carry prep time); send
// prep_min on the ticket if kitchens' times diverge.
const LATE_COOKING_S = 30 * 60;

function riderLine(t: TicketT): { text: string; wait?: boolean } | null {
  const r = t.rider;
  if (!r) {
    if (t.status === "ready") return { text: "Waiting for the rider", wait: true };
    if (t.status === "accepted" || t.status === "preparing") return { text: "Finding a rider…", wait: true };
    return null;
  }
  if (r.phase === "waiting") return { text: `🛵 ${r.name} · at the door` };
  if (r.phase === "to_customer") return { text: `🛵 ${r.name} · picked up` };
  const bits = [`🛵 ${r.name}`];
  if (r.distance_m != null) bits.push(km(r.distance_m));
  if (r.eta_s != null) bits.push(`${minutes(r.eta_s)} min away`);
  else bits.push("on the way");
  return { text: bits.join(" · ") };
}

export function Ticket({
  ticket: t,
  ageS,
  fresh,
  onTransition,
}: {
  ticket: TicketT;
  ageS: number;
  fresh: boolean;
  onTransition: (id: string, to: TransitionTo, reason?: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState<string>(REASONS[0]);
  const [typed, setTyped] = useState("");

  const isNew = t.status === "placed";
  const late = isNew ? ageS >= LATE_S : (t.status === "accepted" || t.status === "preparing") && ageS >= LATE_COOKING_S;
  const rider = riderLine(t);

  async function go(to: TransitionTo, why?: string) {
    if (busy) return;
    setBusy(true);
    try {
      await onTransition(t.id, to, why);
    } finally {
      setBusy(false);
    }
  }

  const finalReason = typed.trim() || reason;

  return (
    <article
      className={`bd-tk${fresh ? " fresh" : ""}${late ? " late" : ""}`}
      style={{ viewTransitionName: `tk-${t.id}` } as CSSProperties}
      aria-label={`Order ${t.number}`}
      aria-busy={busy || undefined}
    >
      <div className="h">
        <span className="num">{t.number}</span>
        <span className={`age num${late ? " late" : ""}`} title="Since the order was placed">
          {late ? "Late · " : ""}
          {age(ageS)}
        </span>
      </div>
      <p className="who">
        {t.customer_first_name} · {t.payment === "cod" ? "COD" : "Paid"} · <span className="num">{inr(t.total_paise)}</span>
      </p>
      <ul aria-label="Items">
        {t.items.map((it, i) => (
          <li key={`${it.name}-${i}`}>
            <span className={`veg${it.is_veg ? "" : " non"}`} role="img" aria-label={it.is_veg ? "Veg" : "Non-veg"} />
            <span>
              <span className="num">{it.qty}</span> × {it.name}
            </span>
          </li>
        ))}
      </ul>
      {t.note && <p className="note">📝 {t.note}</p>}
      {rider && <p className={`rd${rider.wait ? " wait" : ""}`}>{rider.text}</p>}

      {isNew && !rejecting && (
        <div className="btns">
          <button type="button" className="btn reject" disabled={busy} onClick={() => setRejecting(true)}>
            Reject
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => go("accepted")}>
            {busy ? "Accepting…" : "Accept"}
          </button>
        </div>
      )}

      {isNew && rejecting && (
        <form
          className="bd-reasons"
          onSubmit={(e) => {
            e.preventDefault();
            void go("rejected", finalReason);
          }}
        >
          <fieldset>
            <legend className="label">Why reject {t.number}?</legend>
            {REASONS.map((r) => (
              <button
                key={r}
                type="button"
                className="chip"
                aria-pressed={!typed.trim() && reason === r}
                onClick={() => {
                  setReason(r);
                  setTyped("");
                }}
              >
                {r}
              </button>
            ))}
          </fieldset>
          <label className="sr-only" htmlFor={`why-${t.id}`}>
            Or type a reason
          </label>
          <input
            id={`why-${t.id}`}
            className="input"
            placeholder="Or type a reason"
            maxLength={140}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          <div className="btns" style={{ marginTop: 0 }}>
            <button type="button" className="btn ghost" disabled={busy} onClick={() => setRejecting(false)}>
              Keep it
            </button>
            <button type="submit" className="btn coral" disabled={busy}>
              {busy ? "Rejecting…" : "Reject order"}
            </button>
          </div>
        </form>
      )}

      {t.status === "accepted" && (
        <div className="btns">
          <button type="button" className="btn" disabled={busy} onClick={() => go("preparing")}>
            {busy ? "Starting…" : "Start cooking"}
          </button>
        </div>
      )}
      {t.status === "preparing" && (
        <div className="btns">
          <button type="button" className="btn green" disabled={busy} onClick={() => go("ready")}>
            {busy ? "Marking…" : "Mark ready"}
          </button>
        </div>
      )}
    </article>
  );
}
