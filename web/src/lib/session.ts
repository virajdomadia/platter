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

export const HOME_FOR: Record<Role, string> = {
  customer: "/",
  restaurant: "/restaurant",
  rider: "/rider",
  admin: "/admin",
};
