// The rider app (S8): a phone PWA on an ink ground. Riders only; everyone else gets a 404.
import type { Metadata, Viewport } from "next";
import { BodyDark } from "@/components/rider/BodyDark";
import { requireRole } from "@/lib/guard";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Rider", robots: { index: false, follow: false } };
export const viewport: Viewport = { themeColor: "#1F1B2E" };

export default async function RiderLayout({ children }: { children: React.ReactNode }) {
  await requireRole("rider", "/rider");
  return (
    <div style={{ minHeight: "100dvh", background: "#1F1B2E", color: "#F3F0FF" }}>
      <BodyDark />
      {children}
    </div>
  );
}
