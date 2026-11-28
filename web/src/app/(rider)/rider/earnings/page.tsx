import type { Metadata } from "next";
import Link from "next/link";
import { EarningsView } from "@/components/money/Earnings";
import { RoleBar } from "@/components/ui/RoleBar";
import "@/components/rider/rider.css";

export const metadata: Metadata = { title: "Earnings", robots: { index: false } };

export default function RiderEarningsPage() {
  return (
    <main id="main" className="rd" style={{ display: "block" }}>
      <RoleBar title="Earnings" subtitle="₹30 + ₹8 per km for every drop" who="🛵 Rider" dark>
        <Link className="btn small white" href="/rider" style={{ minHeight: 44 }}>
          Back to the job
        </Link>
      </RoleBar>
      <EarningsView path="/rider/earnings" />
    </main>
  );
}
