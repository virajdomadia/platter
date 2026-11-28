"use client";

// S13 earnings (v2 L5), for the kitchen and the rider: what's been earned, what's been paid out,
// what's still owed, and the latest ledger lines. Money is integer paise from the API.
import { useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { day, inr } from "@/lib/format";
import "./money.css";

type Earnings = components["schemas"]["Earnings"];

const KIND: Record<Earnings["entries"][number]["kind"], string> = {
  sale: "Food sale (80%)",
  fee: "Platform fee",
  delivery: "Delivery",
  delivery_margin: "Delivery margin",
  refund: "Refund",
  payout: "Paid out",
};

export function EarningsView({ path }: { path: "/restaurant/earnings" | "/rider/earnings" }) {
  const [data, setData] = useState<Earnings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Earnings>(path)
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, [path]);

  if (error) {
    return (
      <div className="tile peach" role="alert" style={{ marginTop: 10 }}>
        <h2>Couldn&apos;t load earnings</h2>
        <p className="muted">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="mn-grid" aria-busy="true" aria-label="Loading earnings">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton" style={{ height: 110 }} />
        ))}
      </div>
    );
  }
  return (
    <>
      <div className="mn-grid">
        <section className="tile lemon mn-stat spring">
          <span className="label">Owed to you</span>
          <b className="num">{inr(data.balance_paise)}</b>
          <small>earned, not yet paid out</small>
        </section>
        <section className="tile mint mn-stat spring">
          <span className="label">Earned</span>
          <b className="num">{inr(data.earned_paise)}</b>
          <small>from delivered orders</small>
        </section>
        <section className="tile lav mn-stat spring">
          <span className="label">Paid out</span>
          <b className="num">{inr(data.paid_paise)}</b>
          <small>marked paid by Platter</small>
        </section>
      </div>
      <section className="tile mn-list spring" aria-labelledby="mn-h">
        <h2 id="mn-h" style={{ fontSize: 17 }}>
          Latest
        </h2>
        {data.entries.length === 0 ? (
          <p className="muted">Nothing yet. Every delivered order adds a line here.</p>
        ) : (
          <table className="mn-table">
            <thead>
              <tr>
                <th scope="col">What</th>
                <th scope="col">Order</th>
                <th scope="col">When</th>
                <th scope="col" className="num">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((e, i) => (
                <tr key={i}>
                  <td>{KIND[e.kind]}</td>
                  <td className="num">{e.order_number ?? ""}</td>
                  <td>{day(e.at)}</td>
                  <td className={`num ${e.amount_paise < 0 ? "mn-neg" : ""}`}>
                    {e.amount_paise < 0 ? `− ${inr(-e.amount_paise)}` : inr(e.amount_paise)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
