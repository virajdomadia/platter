"use client";

// S13 admin payouts (v2 L5): what each kitchen and rider is owed, a pay form per account (the
// API refuses more than the balance, and a reused reference), and paid-online orders to refund.
// The admin login is the public demo: everything here is the demo's own money.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RoleBar } from "@/components/ui/RoleBar";
import { api, errorMessage } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { inr, STATUS_LABEL } from "@/lib/format";
import { toast } from "@/lib/toast";
import "./money.css";

type Payouts = components["schemas"]["PayoutsOut"];
type Account = Payouts["accounts"][number];

const REFUND: Record<string, string> = {
  pending: "Refund queued",
  sending: "Refund sending",
  processed: "Refunded",
  failed: "Refund failed",
};

export function PayoutsScreen() {
  const [data, setData] = useState<Payouts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<Payouts>("/admin/payouts"));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const pay = async (a: Account, rupees: string, reference: string) => {
    if (busy) return;
    setBusy(a.account);
    try {
      setData(await api<Payouts>("/admin/payouts", { body: { account: a.account, amount_paise: Math.round(Number(rupees) * 100), reference } }));
      toast("Payout recorded", `${a.name}: ₹${rupees}`, "ok");
    } catch (e) {
      toast(`Couldn't pay ${a.name}`, errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const refund = async (id: string, number: string) => {
    if (busy || !window.confirm(`Refund ${number} in full to the customer's payment method?`)) return;
    setBusy(id);
    try {
      const r = await api<{ refund: { status: string } | null }>(`/admin/orders/${id}/refund`, { method: "POST" });
      toast(r.refund?.status === "processed" ? `${number} refunded` : `${number}: ${REFUND[r.refund?.status ?? "pending"]}`, undefined, r.refund?.status === "processed" ? "ok" : undefined);
      await load();
    } catch (e) {
      toast(`Couldn't refund ${number}`, errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <RoleBar title="Payouts" subtitle="Money owed to kitchens and riders" who="👑 Admin">
        <Link className="btn small ghost" href="/admin" style={{ minHeight: 44 }}>
          Live map
        </Link>
      </RoleBar>

      {error && !data && (
        <div className="tile peach" role="alert" style={{ marginTop: 10 }}>
          <h2>Couldn&apos;t load payouts</h2>
          <p className="muted">{error}</p>
        </div>
      )}
      {!data && !error && <div className="skeleton" style={{ height: 300, marginTop: 10 }} aria-busy="true" aria-label="Loading payouts" />}

      {data && (
        <>
          <p className="tile lemon" role="note" style={{ marginTop: 10, fontWeight: 800 }}>
            Every delivered order splits its money: 80% of the food to the kitchen, ₹30 + ₹8/km to the rider, the rest to Platter. This is the
            public demo&apos;s ledger.
          </p>
          <div className="mn-grid">
            <section className="tile mint mn-stat">
              <span className="label">Platter&apos;s share</span>
              <b className="num">{inr(data.platform_paise)}</b>
              <small>fees and delivery margin, less refunds</small>
            </section>
            <section className="tile lav mn-stat">
              <span className="label">Owed out</span>
              <b className="num">{inr(data.accounts.reduce((n, a) => n + a.balance_paise, 0))}</b>
              <small>across {data.accounts.length} accounts</small>
            </section>
          </div>

          <section className="tile mn-list" aria-labelledby="acc-h">
            <h2 id="acc-h" style={{ fontSize: 17 }}>
              Balances
            </h2>
            {data.accounts.length === 0 ? (
              <p className="muted">No delivered orders yet.</p>
            ) : (
              <div className="mn-scroll">
                <table className="mn-table mn-accounts">
                  <thead>
                    <tr>
                      <th scope="col">Account</th>
                      <th scope="col" className="num">
                        Owed
                      </th>
                      <th scope="col" className="num">
                        Paid
                      </th>
                      <th scope="col">Pay out</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.accounts.map((a) => (
                      <AccountRow key={a.account} a={a} busy={busy === a.account} onPay={pay} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="tile mn-list" aria-labelledby="ref-h">
            <h2 id="ref-h" style={{ fontSize: 17 }}>
              Paid online
            </h2>
            {data.refundable.length === 0 ? (
              <p className="muted">No closed orders paid online. Cash orders have nothing to refund.</p>
            ) : (
              <div className="mn-scroll">
                <table className="mn-table">
                  <thead>
                    <tr>
                      <th scope="col">Order</th>
                      <th scope="col">Status</th>
                      <th scope="col" className="num">
                        Total
                      </th>
                      <th scope="col">Refund</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.refundable.map((o) => (
                      <tr key={o.id}>
                        <td className="num" style={{ textAlign: "left" }}>
                          {o.number}
                        </td>
                        <td>{STATUS_LABEL[o.status]}</td>
                        <td className="num">{inr(o.total_paise)}</td>
                        <td>
                          {o.refund && o.refund.status !== "failed" ? (
                            <span className={`chip ${o.refund.status === "processed" ? "mint" : "lemon"}`}>{REFUND[o.refund.status]}</span>
                          ) : (
                            <button type="button" className="btn small ghost" aria-disabled={busy !== null} onClick={() => void refund(o.id, o.number)}>
                              {o.refund ? "Retry refund" : "Refund"}
                              <span className="sr-only"> {o.number}</span>
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}

function AccountRow({ a, busy, onPay }: { a: Account; busy: boolean; onPay: (a: Account, rupees: string, ref: string) => void }) {
  const [rupees, setRupees] = useState(String(a.balance_paise / 100));
  const [ref, setRef] = useState("");
  useEffect(() => setRupees(String(a.balance_paise / 100)), [a.balance_paise]);
  const amount = Number(rupees);
  const ok = a.balance_paise > 0 && amount > 0 && amount * 100 <= a.balance_paise && ref.trim().length > 0;
  return (
    <tr>
      <td>
        <b>{a.name}</b>
        <br />
        <small className="muted">{a.kind === "restaurant" ? "Kitchen" : "Rider"}</small>
      </td>
      <td className="num">
        {inr(a.balance_paise)}
        <small className="mn-cap" aria-hidden="true"> owed</small>
      </td>
      <td className="num">
        {inr(a.paid_paise)}
        <small className="mn-cap" aria-hidden="true"> paid</small>
      </td>
      <td>
        {a.balance_paise === 0 ? (
          <span className="muted">Nothing owed</span>
        ) : (
        <form
          className="mn-pay"
          onSubmit={(e) => {
            e.preventDefault();
            if (ok && !busy) onPay(a, rupees, ref.trim());
          }}
        >
          <label className="sr-only" htmlFor={`amt-${a.account}`}>
            Amount in rupees for {a.name}
          </label>
          <input
            id={`amt-${a.account}`}
            className="input num"
            type="number"
            min={1}
            step="0.01"
            max={a.balance_paise / 100}
            value={rupees}
            onChange={(e) => setRupees(e.target.value)}
          />
          <label className="sr-only" htmlFor={`ref-${a.account}`}>
            Payment reference for {a.name}
          </label>
          <input
            id={`ref-${a.account}`}
            className="input"
            placeholder="UPI / bank ref"
            maxLength={60}
            value={ref}
            onChange={(e) => setRef(e.target.value)}
          />
          <button className="btn small" aria-disabled={!ok || busy}>
            {busy ? "Paying…" : "Mark paid"}
          </button>
        </form>
        )}
      </td>
    </tr>
  );
}
