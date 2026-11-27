"use client";

import { useEffect, useSyncExternalStore } from "react";
import { api, type Me, type Role } from "./api";

// The signed-in user, fetched once per tab and shared (undefined = still loading, null = signed out).
let me: Me | null | undefined;
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

function load(): Promise<void> {
  loading ??= api<Me>("/auth/me")
    .then((m) => {
      me = m;
    })
    .catch(() => {
      me = null;
    })
    .finally(() => listeners.forEach((l) => l()));
  return loading;
}

export function setMe(next: Me | null): void {
  me = next;
  loading = Promise.resolve();
  listeners.forEach((l) => l());
}

export function useMe(): Me | null | undefined {
  const value = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => me,
    () => undefined,
  );
  useEffect(() => {
    if (me === undefined) void load();
  }, []);
  return value;
}

export async function signOut(): Promise<void> {
  await api("/auth/sign-out", { method: "POST" });
  setMe(null);
}

/** A same-origin path to go to after sign-in, else null. Parsed like the browser will parse it, so
 * `/\evil.com` (a backslash reads as `//`) can't send anyone off-site. */
export function safeNext(next: string | null, origin = "https://platter.invalid"): string | null {
  if (!next || !next.startsWith("/")) return null;
  try {
    const u = new URL(next, origin);
    return u.origin === origin ? u.pathname + u.search + u.hash : null;
  } catch {
    return null;
  }
}

export const HOME_FOR: Record<Role, string> = {
  customer: "/",
  restaurant: "/restaurant",
  rider: "/rider",
  admin: "/admin",
};
