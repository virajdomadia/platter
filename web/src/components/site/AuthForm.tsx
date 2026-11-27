"use client";

// S10: email + password, with the four demo cards one tap away.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { api, ApiError, errorMessage, type Me } from "@/lib/api";
import { HOME_FOR, safeNext, setMe } from "@/lib/session";
import { DemoCards } from "./DemoCards";

export function AuthForm({ mode }: { mode: "sign-in" | "sign-up" }) {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [form, setForm] = useState({ name: "", email: "", password: "", phone: "" });
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const up = mode === "sign-up";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFields({});
    try {
      const body = up ? { ...form, phone: form.phone || undefined } : { email: form.email, password: form.password };
      const me = await api<Me>(`/auth/${mode}`, { body });
      setMe(me);
      router.push(me.role === "customer" ? next ?? "/" : HOME_FOR[me.role]);
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.details.fields) setFields(err.details.fields as Record<string, string>);
      setBusy(false);
    }
  };

  const field = (key: keyof typeof form, label: string, props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <label className="field">
      <span className="label">{label}</span>
      <input className="input" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} aria-invalid={!!fields[key]} {...props} />
      {fields[key] && <span className="error-text">{fields[key]}</span>}
    </label>
  );

  return (
    <main id="main" className="page narrow">
      <div className="stack">
        <div className="tile spring">
          <h1 style={{ fontSize: 26 }}>{up ? "Create your account" : "Welcome back"}</h1>
          <p className="muted" style={{ marginTop: 4 }}>
            {up ? "Order from kitchens near you and watch the rider come to your door." : "Sign in, or try any side of the platform in one tap below."}
          </p>
          <form onSubmit={submit} className="stack" style={{ marginTop: 14 }} noValidate={false}>
            {up && field("name", "Your name", { required: true, maxLength: 80, autoComplete: "name" })}
            {field("email", "Email", { type: "email", required: true, autoComplete: "email" })}
            {field("password", "Password", { type: "password", required: true, minLength: up ? 8 : 1, autoComplete: up ? "new-password" : "current-password" })}
            {up && field("phone", "Phone (optional)", { type: "tel", maxLength: 20, autoComplete: "tel" })}
            {error && <p className="error-text" role="alert">{error}</p>}
            <button className="btn block" disabled={busy}>
              {busy ? "One moment…" : up ? "Create account →" : "Sign in →"}
            </button>
          </form>
          <p style={{ marginTop: 12, fontSize: 14 }}>
            {up ? "Already have an account? " : "New here? "}
            <Link href={`/${up ? "sign-in" : "sign-up"}${next ? `?next=${encodeURIComponent(next)}` : ""}`}>{up ? "Sign in" : "Create an account"}</Link>
          </p>
        </div>
        <h2 className="label" style={{ margin: "8px 6px 0" }}>Try a demo login</h2>
        <DemoCards next={next ?? undefined} compact />
      </div>
    </main>
  );
}
