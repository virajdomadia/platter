// The admin live map (S9). Admins only; everyone else gets a 404.
import type { Metadata } from "next";
import { requireRole } from "@/lib/guard";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Admin", robots: { index: false, follow: false } };

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  await requireRole("admin", "/admin");
  return (
    <main id="main" className="page" style={{ width: "min(1440px, 100% - 24px)" }}>
      {children}
    </main>
  );
}
