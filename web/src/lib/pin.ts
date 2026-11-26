// The delivery pin (R2): browser geolocation with permission, else the last saved address, else the
// seed default — Koramangala 5th Block. Kept in localStorage so every page agrees.
import { useSyncExternalStore } from "react";
import { DEFAULT_PIN } from "./geo";

export type Pin = { lat: number; lng: number; label: string; line: string; addressId?: string };

const KEY = "platter.pin.v1";
const listeners = new Set<() => void>();
let cached: Pin | undefined;

function read(): Pin {
  if (cached) return cached;
  try {
    const raw = localStorage.getItem(KEY);
    cached = raw ? (JSON.parse(raw) as Pin) : DEFAULT_PIN;
  } catch {
    cached = DEFAULT_PIN;
  }
  return cached;
}

export function hasSavedPin(): boolean {
  try {
    return localStorage.getItem(KEY) !== null;
  } catch {
    return false;
  }
}

export function setPin(pin: Pin): void {
  cached = pin;
  try {
    localStorage.setItem(KEY, JSON.stringify(pin));
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function usePin(): Pin {
  return useSyncExternalStore(subscribe, read, () => DEFAULT_PIN);
}
