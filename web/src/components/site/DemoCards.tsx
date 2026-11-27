"use client";

// The four demo logins (S10): one tap signs in as a seeded account, and the API makes sure there is
// something alive to see — an order on the way, tickets on the board, a job, orders on the map.
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage, type Me, type Role } from "@/lib/api";
import { HOME_FOR, setMe } from "@/lib/session";
import { toast } from "@/lib/toast";

const CARDS: { role: Role; tone: string; icon: string; title: string; body: string }[] = [
  { role: "customer", tone: "lav", icon: "🙂", title: "Customer", body: "Ananya · 3 saved addresses, an order on the way" },
  { role: "restaurant", tone: "sky", icon: "🍳", title: "Restaurant", body: "Bandstand Kitchen's kitchen board, tickets printing" },
  { role: "rider", tone: "lemon", icon: "🛵", title: "Rider", body: "A job assigned — share your location and walk" },
  { role: "admin", tone: "peach", icon: "🗺️", title: "Admin", body: "Every order and rider on one live map" },
];

export function DemoCards({ next, compact }: { next?: string; compact?: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState<Role | null>(null);
  return (
    <div className="grid2" style={compact ? undefined : { gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
      {CARDS.map((c) => (
        <button
          key={c.role}
          className={`tile ${c.tone} spring`}
          style={{ textAlign: "left", border: 0, display: "grid", gap: 4, minHeight: 116, alignContent: "start" }}
          disabled={busy !== null}
          aria-busy={busy === c.role}
          onClick={async () => {
            setBusy(c.role);
            try {
              const me = await api<Me>("/auth/demo", { body: { as: c.role } });
              setMe(me);
              router.push(c.role === "customer" && next ? next : HOME_FOR[c.role]);
              router.refresh();
            } catch (err) {
              toast("Couldn't sign in", errorMessage(err));
              setBusy(null);
            }
          }}
        >
          <span style={{ fontSize: 26 }} aria-hidden="true">
            {c.icon}
          </span>
          <b style={{ fontWeight: 900, fontSize: 15 }}>{busy === c.role ? "Signing in…" : c.title}</b>
          <small style={{ fontWeight: 700, fontSize: 12, color: "var(--ink2)" }}>{c.body}</small>
        </button>
      ))}
    </div>
  );
}
