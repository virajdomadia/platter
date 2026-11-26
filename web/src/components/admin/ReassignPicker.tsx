"use client";

// Pick a rider for an order (R9): riders nearest the restaurant, available first. Only available
// riders can be chosen; busy/offline rows say why.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage, type AdminOrder, type AdminRider } from "@/lib/api";
import { km } from "@/lib/format";
import { toast } from "@/lib/toast";

export function ReassignPicker({
  order,
  onClose,
  onDone,
}: {
  order: AdminOrder;
  onClose: () => void;
  onDone: () => void;
}) {
  const [riders, setRiders] = useState<AdminRider[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  const load = async (signal?: AbortSignal) => {
    setError(null);
    try {
      const near = `${order.restaurant.lat},${order.restaurant.lng}`;
      setRiders(await api<AdminRider[]>(`/admin/riders?near=${encodeURIComponent(near)}`, { signal }));
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError(errorMessage(err));
    }
  };

  useEffect(() => {
    const ctl = new AbortController();
    void load(ctl.signal);
    return () => ctl.abort();
    // the picker is opened for one order and closed afterwards
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // focus in, Esc closes, Tab stays inside, focus goes back to the opener on close
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    box.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !box.current) return;
      const items = box.current.querySelectorAll<HTMLElement>("button:not(:disabled), [href], [tabindex]:not([tabindex='-1'])");
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === box.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, []);

  const assign = async (r: AdminRider) => {
    setSaving(r.id);
    try {
      await api<AdminOrder>(`/admin/orders/${order.id}/reassign`, { body: { rider_id: r.id } });
      toast(`${order.number} → ${r.name}`, undefined, "ok");
      onDone();
    } catch (err) {
      toast(errorMessage(err));
      if (err instanceof ApiError && err.status === 409) void load();
    } finally {
      setSaving(null);
    }
  };

  return (
    <>
      <div className="sheet-dim" onClick={onClose} aria-hidden="true" />
      <div
        ref={box}
        className="ad-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pick-h"
        tabIndex={-1}
      >
        <div className="between">
          <div>
            <h2 id="pick-h">{order.rider_id ? "Reassign" : "Assign"} {order.number}</h2>
            <p className="muted">
              {order.restaurant_name}
              {order.rider_name ? ` · now with ${order.rider_name}` : " · no rider yet"}
            </p>
          </div>
          <button type="button" className="btn small ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {error && (
          <div className="tile peach" role="alert" style={{ marginTop: 12 }}>
            <p>{error}</p>
            <button type="button" className="btn small" style={{ marginTop: 8 }} onClick={() => void load()}>
              Retry
            </button>
          </div>
        )}
        {!riders && !error && (
          <div className="stack" style={{ marginTop: 12 }} aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton" style={{ height: 56 }} />
            ))}
          </div>
        )}
        {riders && riders.length === 0 && <p className="muted" style={{ marginTop: 12 }}>No riders on the platform yet.</p>}
        {riders && riders.length > 0 && (
          <ul className="ad-riders">
            {riders.map((r) => {
              const current = r.id === order.rider_id;
              const why = current
                ? "Already on it"
                : r.status === "busy"
                  ? `Busy${r.current_order ? ` · ${r.current_order}` : ""}`
                  : r.status === "offline"
                    ? "Offline"
                    : null;
              return (
                <li key={r.id}>
                  <div style={{ minWidth: 0 }}>
                    <b>{r.name}</b>{" "}
                    <span className={`chip ${r.is_sim ? "lav" : "mint"}`}>{r.is_sim ? "sim" : "real"}</span>
                    <p className="muted num">
                      {r.status}
                      {r.distance_m != null ? ` · ${km(r.distance_m)} away` : ""}
                      {r.current_order ? ` · on ${r.current_order}` : ""}
                    </p>
                  </div>
                  {why ? (
                    <button type="button" className="btn small ghost" disabled>
                      {why}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn small"
                      disabled={saving !== null}
                      onClick={() => void assign(r)}
                    >
                      {saving === r.id ? "Assigning…" : "Assign"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </>
  );
}
