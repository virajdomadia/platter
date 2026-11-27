"use client";

import { useSyncExternalStore } from "react";

export type Toast = { id: number; title: string; body?: string; tone?: "ok" | "warn" };

let current: Toast | null = null;
let timer: number | undefined;
const listeners = new Set<() => void>();

export function toast(title: string, body?: string, tone: Toast["tone"] = "warn"): void {
  current = { id: Date.now(), title, body, tone };
  listeners.forEach((l) => l());
  window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    current = null;
    listeners.forEach((l) => l());
  }, 5000);
}

export function useToast(): Toast | null {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => current,
    () => null,
  );
}
