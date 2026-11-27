"use client";

// S6 Reorder (v2 L4): the past order becomes the cart at today's prices; anything gone from the
// menu is named, never silently dropped. Checkout quotes it again as usual.
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { saveCart, useCart } from "@/lib/cart";
import { toast } from "@/lib/toast";

type Reorder = {
  restaurant: { id: string; slug: string; name: string };
  lines: { id: string; name: string; price_paise: number; qty: number; is_veg: boolean; photo: string | null }[];
  dropped: string[];
};

export function ReorderButton({ orderId, number }: { orderId: string; number: string }) {
  const router = useRouter();
  const cart = useCart();
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (busy) return; // aria-disabled keeps focus but doesn't stop a double tap
    setBusy(true);
    try {
      const r = await api<Reorder>(`/orders/${orderId}/reorder`, { method: "POST" });
      if (r.lines.length === 0) {
        toast("Nothing to reorder", `${r.dropped.join(", ")} ${r.dropped.length === 1 ? "isn't" : "aren't"} on the menu right now.`);
        return;
      }
      if (cart && cart.lines.length && !window.confirm(`Replace your ${cart.restaurant.name} cart with ${number}?`)) return;
      saveCart({ restaurant: r.restaurant, lines: r.lines, note: "" });
      if (r.dropped.length) toast("Added what's still on the menu", `Not available now: ${r.dropped.join(", ")}.`);
      else toast("Added to your cart", `${r.restaurant.name}, at today's prices.`, "ok");
      router.push(`/r/${r.restaurant.slug}`);
    } catch (err) {
      toast("Couldn't reorder", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" className="btn small white" onClick={() => void go()} aria-disabled={busy}>
      {busy ? "Adding…" : "Reorder"}
      <span className="sr-only"> {number}</span>
    </button>
  );
}
