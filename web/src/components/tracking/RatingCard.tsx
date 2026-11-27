"use client";

// S5 after delivery (v2 L4): one rating per order. Stars are a plain radio group (arrow keys move,
// every option is named); a note is optional. Once sent it shows what you gave.
import { useState } from "react";
import { api, errorMessage, type OrderOut } from "@/lib/api";
import { toast } from "@/lib/toast";

function Stars({ name, legend, value, onChange }: { name: string; legend: string; value: number; onChange: (n: number) => void }) {
  return (
    <fieldset className="stars">
      <legend className="label">{legend}</legend>
      <div className="stars-row">
        {[1, 2, 3, 4, 5].map((n) => (
          <label key={n} className={n <= value ? "on" : undefined}>
            <input type="radio" name={name} value={n} checked={value === n} onChange={() => onChange(n)} />
            <span aria-hidden="true">★</span>
            <span className="sr-only">
              {n} star{n === 1 ? "" : "s"}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function RatingCard({ order, onRated }: { order: OrderOut; onRated: (o: OrderOut) => void }) {
  const [kitchen, setKitchen] = useState(0);
  const [rider, setRider] = useState(0);
  const [line, setLine] = useState("");
  const [busy, setBusy] = useState(false);
  const done = order.rating;

  if (done) {
    return (
      <section className="rate-tile" aria-labelledby="rate-h">
        <h2 id="rate-h" style={{ fontSize: 16 }}>
          Thanks for rating
        </h2>
        <p>
          {order.restaurant.name}: <span aria-hidden="true">{"★".repeat(done.restaurant_stars)}</span>
          <span className="sr-only">{done.restaurant_stars} of 5 stars</span>
          {done.rider_stars && order.rider && (
            <>
              {" "}
              · {order.rider.name.split(" ")[0]}: <span aria-hidden="true">{"★".repeat(done.rider_stars)}</span>
              <span className="sr-only">{done.rider_stars} of 5 stars</span>
            </>
          )}
        </p>
        {done.line && <p className="muted">“{done.line}”</p>}
      </section>
    );
  }

  const send = async () => {
    setBusy(true);
    try {
      const body = { restaurant_stars: kitchen, rider_stars: rider || null, line: line.trim() || null };
      onRated(await api<OrderOut>(`/orders/${order.id}/rating`, { body }));
      toast("Thanks for rating", undefined, "ok");
    } catch (err) {
      toast("Couldn't send your rating", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="rate-tile"
      aria-labelledby="rate-h"
      onSubmit={(e) => {
        e.preventDefault();
        if (kitchen) void send();
      }}
    >
      <h2 id="rate-h" style={{ fontSize: 16 }}>
        How was it?
      </h2>
      <Stars name="kitchen" legend={order.restaurant.name} value={kitchen} onChange={setKitchen} />
      {order.rider && <Stars name="rider" legend={`${order.rider.name.split(" ")[0]}, your rider (optional)`} value={rider} onChange={setRider} />}
      <label className="field">
        <span className="label">A note (optional)</span>
        <textarea className="input" maxLength={280} value={line} onChange={(e) => setLine(e.target.value)} />
      </label>
      <button className="btn small" aria-disabled={!kitchen || busy} disabled={busy}>
        {busy ? "Sending…" : kitchen ? "Send rating" : "Pick the kitchen's stars first"}
      </button>
    </form>
  );
}
