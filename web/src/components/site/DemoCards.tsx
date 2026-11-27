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
  { role: "rider", tone: "lemon", icon: "🛵", title: "Rider", body: "A job assigned: share your location and walk" },
  { role: "admin", tone: "peach", icon: "🗺️", title: "Admin", body: "Every order and rider on one live map" },
];

export function DemoCards({ next, compact, strip }: { next?: string; compact?: boolean; strip?: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState<Role | null>(null);
  const go = async (role: Role) => {
    setBusy(role);
    try {
      const me = await api<Me>("/auth/demo", { body: { as: role } });
      setMe(me);
      router.push(role === "customer" && next ? next : HOME_FOR[role]);
      router.refresh();
    } catch (err) {
      toast("Couldn't sign in", errorMessage(err));
      setBusy(null);
    }
  };
  if (strip) {
    // The recruiter's way in, near the top of the home page (the full cards repeat lower down).
    return (
      <div className="row" role="group" aria-label="Try the demo as" style={{ flexWrap: "wrap", gap: 6 }}>
        {CARDS.map((c) => (
          <button key={c.role} className="chip white demo-chip" disabled={busy !== null} aria-busy={busy === c.role} onClick={() => go(c.role)}>
            <span aria-hidden="true">{c.icon}</span>
            {busy === c.role ? "Signing in…" : c.title}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className="grid2" style={compact ? undefined : { gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
      {CARDS.map((c) => (
        <button
          key={c.role}
          className={`tile ${c.tone} spring`}
          style={{ textAlign: "left", border: 0, display: "grid", gap: 4, minHeight: 116, alignContent: "start" }}
          disabled={busy !== null}
          aria-busy={busy === c.role}
          onClick={() => go(c.role)}
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
