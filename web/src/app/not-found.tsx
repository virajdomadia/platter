import type { Metadata } from "next";
import Link from "next/link";
import { LogoMark } from "@/components/ui/Logo";

export const metadata: Metadata = { title: "Page not found", robots: { index: false } };

export default function NotFound() {
  return (
    <main id="main" className="page narrow" style={{ paddingTop: 40 }}>
      <div className="tile lav spring" style={{ display: "grid", gap: 10, justifyItems: "start" }}>
        <LogoMark size={44} />
        <span className="chip white">404</span>
        <h1 style={{ fontSize: 28 }}>This address isn&apos;t on our map</h1>
        <p className="muted">The page doesn&apos;t exist, or it isn&apos;t yours to see.</p>
        <Link className="btn" href="/">Back to Platter</Link>
      </div>
    </main>
  );
}
