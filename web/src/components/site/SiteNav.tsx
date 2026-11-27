"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LogoMark } from "@/components/ui/Logo";
import { HOME_FOR, signOut, useMe } from "@/lib/session";

const LINKS = [
  { href: "/", label: "Home", icon: "🏠" },
  { href: "/orders", label: "Orders", icon: "🧾" },
  { href: "/addresses", label: "Addresses", icon: "📍" },
];

function current(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function TopBar() {
  const me = useMe();
  const pathname = usePathname();
  const router = useRouter();
  return (
    <div className="topbar page" style={{ paddingBottom: 0 }}>
      <nav className="tile" aria-label="Main">
        <Link href="/" className="brand">
          <LogoMark />
          Platter
        </Link>
        <div className="topnav">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} aria-current={current(pathname, l.href) ? "page" : undefined}>
              {l.label}
            </Link>
          ))}
          {me && me.role !== "customer" && <Link href={HOME_FOR[me.role]}>My {me.role === "admin" ? "admin" : me.role === "rider" ? "rider app" : "kitchen"} →</Link>}
        </div>
        <div className="row" style={{ marginLeft: "auto" }}>
          {me === undefined ? (
            <span className="chip" aria-hidden="true" style={{ width: 90, height: 34 }} />
          ) : me ? (
            <>
              <span className="chip lav" title={me.email}>
                🙂 {me.name.split(" ")[0]}
              </span>
              <button
                className="btn small ghost"
                onClick={async () => {
                  await signOut().catch(() => undefined);
                  router.refresh();
                }}
              >
                Sign out
              </button>
            </>
          ) : (
            <Link className="btn small" href={`/sign-in?next=${encodeURIComponent(pathname)}`}>
              Sign in
            </Link>
          )}
        </div>
      </nav>
    </div>
  );
}

export function BottomNav() {
  const pathname = usePathname();
  const me = useMe();
  return (
    <nav className="bottomnav" aria-label="Main">
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} aria-current={current(pathname, l.href) ? "page" : undefined}>
          <span aria-hidden="true">{l.icon}</span>
          {l.label}
        </Link>
      ))}
      <Link href={me ? (me.role === "customer" ? "/orders" : HOME_FOR[me.role]) : "/sign-in"} aria-current={pathname.startsWith("/sign") ? "page" : undefined}>
        <span aria-hidden="true">🙂</span>
        {me ? me.name.split(" ")[0] : "Sign in"}
      </Link>
    </nav>
  );
}
