// One cart, one restaurant, kept in localStorage (R3). Pure functions + a tiny store for
// useSyncExternalStore; prices here are for display only — the API prices every order itself.
import { useSyncExternalStore } from "react";

export type CartLine = {
  id: string;
  name: string;
  price_paise: number;
  qty: number;
  is_veg: boolean;
  photo: string | null;
};
export type Cart = {
  restaurant: { id: string; slug: string; name: string };
  lines: CartLine[];
  note: string;
};

const KEY = "platter.cart.v1";
export const MAX_QTY = 20;

export function count(cart: Cart | null): number {
  return cart ? cart.lines.reduce((n, l) => n + l.qty, 0) : 0;
}

export function subtotal(cart: Cart | null): number {
  return cart ? cart.lines.reduce((n, l) => n + l.qty * l.price_paise, 0) : 0;
}

export function qtyOf(cart: Cart | null, itemId: string): number {
  return cart?.lines.find((l) => l.id === itemId)?.qty ?? 0;
}

/** Add one; `conflict` when the cart holds another restaurant's food (one restaurant per order). */
export function add(
  cart: Cart | null,
  restaurant: Cart["restaurant"],
  item: Omit<CartLine, "qty">,
): { cart: Cart | null; conflict: boolean } {
  if (cart && cart.lines.length && cart.restaurant.id !== restaurant.id) return { cart, conflict: true };
  const base: Cart = cart && cart.restaurant.id === restaurant.id ? cart : { restaurant, lines: [], note: "" };
  const existing = base.lines.find((l) => l.id === item.id);
  const lines = existing
    ? base.lines.map((l) => (l.id === item.id ? { ...l, qty: Math.min(MAX_QTY, l.qty + 1) } : l))
    : [...base.lines, { ...item, qty: 1 }];
  return { cart: { ...base, lines }, conflict: false };
}

export function setQty(cart: Cart, itemId: string, qty: number): Cart | null {
  const lines = cart.lines
    .map((l) => (l.id === itemId ? { ...l, qty: Math.min(MAX_QTY, qty) } : l))
    .filter((l) => l.qty > 0);
  return lines.length ? { ...cart, lines } : null;
}

export function drop(cart: Cart, ids: string[]): Cart | null {
  const lines = cart.lines.filter((l) => !ids.includes(l.id));
  return lines.length ? { ...cart, lines } : null;
}

// --- store ------------------------------------------------------------------------------------

const listeners = new Set<() => void>();
let cached: Cart | null | undefined;

function read(): Cart | null {
  if (cached !== undefined) return cached;
  try {
    const raw = localStorage.getItem(KEY);
    cached = raw ? (JSON.parse(raw) as Cart) : null;
  } catch {
    cached = null;
  }
  return cached;
}

export function saveCart(next: Cart | null): void {
  cached = next;
  try {
    if (next) localStorage.setItem(KEY, JSON.stringify(next));
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: the cart lives for this tab only */
  }
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      cached = undefined;
      cb();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export function useCart(): Cart | null {
  return useSyncExternalStore(subscribe, read, () => null);
}
