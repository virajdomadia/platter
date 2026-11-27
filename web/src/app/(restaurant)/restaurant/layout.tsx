import type { Metadata } from "next";
import { requireRole } from "@/lib/guard";

export const metadata: Metadata = { title: "Kitchen board", robots: { index: false } };
export const dynamic = "force-dynamic";

export default async function RestaurantLayout({ children }: { children: React.ReactNode }) {
  await requireRole("restaurant", "/restaurant");
  return (
    <main id="main" className="page" style={{ width: "min(1400px, 100% - 24px)" }}>
      {children}
    </main>
  );
}
