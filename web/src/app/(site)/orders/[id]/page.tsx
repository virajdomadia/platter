import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { TrackingScreen } from "@/components/tracking/TrackingScreen";
import type { OrderOut } from "@/lib/api";
import { serverFetch } from "@/lib/server";
import "@/components/site/site.css";

export const metadata: Metadata = { title: "Tracking your order", robots: { index: false } };
export const dynamic = "force-dynamic";

export default async function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const { status, data } = await serverFetch<OrderOut>(`/orders/${id}`, { auth: true });
  if (status === 401) redirect(`/sign-in?next=/orders/${id}`);
  if (status === 404) notFound();
  if (!data) throw new Error("The order service is unreachable");
  return <TrackingScreen initial={data} />;
}
