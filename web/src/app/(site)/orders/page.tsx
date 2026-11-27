import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { redirect } from "next/navigation";
import type { OrderCard } from "@/lib/api";
import { day, inr, STATUS_LABEL } from "@/lib/format";
import { serverFetch } from "@/lib/server";
import { ReorderButton } from "@/components/site/ReorderButton";
import "@/components/site/site.css";

export const metadata: Metadata = { title: "Your orders", robots: { index: false } };
export const dynamic = "force-dynamic";

const TONE: Record<string, string> = {
  delivered: "lav",
  rejected: "peach",
  cancelled: "peach",
  expired: "peach",
};

export default async function OrdersPage() {
  const { status, data } = await serverFetch<OrderCard[]>("/orders", { auth: true });
  if (status === 401) redirect("/sign-in?next=/orders");
  if (!data) throw new Error("Orders are unreachable right now");
  const active = data.filter((o) => !TONE[o.status]);
  const past = data.filter((o) => TONE[o.status]);
  return (
    <main id="main" className="page narrow">
      <h1 style={{ fontSize: 24, margin: "6px 4px 12px" }}>Your orders</h1>
      {data.length === 0 && (
        <div className="tile lemon spring">
          <p style={{ fontSize: 28 }} aria-hidden="true">🧾</p>
          <h2 style={{ fontSize: 18 }}>No orders yet</h2>
          <p className="muted" style={{ marginTop: 4 }}>Your first dosa is about 22 minutes away.</p>
          <Link className="btn" href="/" style={{ marginTop: 12 }}>Browse kitchens</Link>
        </div>
      )}
      {active.length > 0 && <h2 className="label" style={{ margin: "4px 6px 8px" }}>On the way</h2>}
      <div className="stack">
        {active.map((o) => <Row key={o.id} o={o} />)}
      </div>
      {past.length > 0 && <h2 className="label" style={{ margin: "16px 6px 8px" }}>Earlier</h2>}
      <div className="stack">
        {past.map((o) => (
          <div key={o.id} className="order-past">
            <Row o={o} />
            <ReorderButton orderId={o.id} number={o.number} />
          </div>
        ))}
      </div>
    </main>
  );
}

function Row({ o }: { o: OrderCard }) {
  const tone = TONE[o.status] ?? "mint";
  return (
    <Link href={`/orders/${o.id}`} className="tile order-row spring">
      {o.cover ? <Image src={o.cover.url} alt="" width={64} height={64} /> : <span aria-hidden="true">🍽️</span>}
      <div style={{ minWidth: 0 }}>
        <b>{o.restaurant_name}</b>
        <small>{o.items_summary}</small>
        <small className="num">{o.number} · {day(o.created_at)} · {inr(o.total_paise)}</small>
      </div>
      <span className={`chip ${tone}`}>
        {tone === "mint" ? `${STATUS_LABEL[o.status]} · Track →` : STATUS_LABEL[o.status]}
      </span>
    </Link>
  );
}
