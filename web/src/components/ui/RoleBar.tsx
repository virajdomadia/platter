"use client";

// The top tile on the restaurant board, the rider app and the admin: brand, where you are, who you
// are, sign out.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogoMark } from "./Logo";
import { signOut } from "@/lib/session";

export function RoleBar({
  title,
  subtitle,
  who,
  dark,
  children,
}: {
  title: string;
  subtitle?: string;
  who: string;
  dark?: boolean;
  children?: React.ReactNode;
}) {
  const router = useRouter();
  return (
    <header className={`tile ${dark ? "ink2" : ""}`} style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "10px 14px" }}>
      <Link href="/" className="brand" aria-label="Platter home">
        <LogoMark />
      </Link>
      <div style={{ minWidth: 0 }}>
        <h1 style={{ fontSize: 18 }}>{title}</h1>
        {subtitle && (
          <p className="label" style={{ textTransform: "none", letterSpacing: 0, fontSize: 12 }}>
            {subtitle}
          </p>
        )}
      </div>
      <div className="row" style={{ marginLeft: "auto", flexWrap: "wrap" }}>
        {children}
        <span className={`chip ${dark ? "dark" : ""}`} title="Signed in">
          {who}
        </span>
        <button
          className={`btn small ${dark ? "white" : "ghost"}`}
          style={{ minHeight: 44 }}
          onClick={async () => {
            await signOut().catch(() => undefined);
            router.push("/sign-in");
            router.refresh();
          }}
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
