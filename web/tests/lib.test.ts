import { describe, expect, test } from "vitest";
import { add, count, drop, qtyOf, setQty, subtotal, type Cart } from "@/lib/cart";
import { etaLabel, inr, km } from "@/lib/format";
import { bearing, cumulative, decode, haversine, lerpAngle, project, slice } from "@/lib/geo";
import { liveReducer, type Live } from "@/lib/stream";
import type { OrderOut } from "@/lib/api";
import { safeNext } from "@/lib/session";

describe("geo", () => {
  test("decodes Google's reference polyline", () => {
    expect(decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@")).toEqual([
      [38.5, -120.2],
      [40.7, -120.95],
      [43.252, -126.453],
    ]);
  });

  test("haversine, bearing and projection agree with the API's maths", () => {
    const line: [number, number][] = [
      [12.93, 77.62],
      [12.93, 77.63],
      [12.94, 77.63],
    ];
    const cum = cumulative(line);
    const first = haversine(line[0], line[1]);
    expect(first).toBeGreaterThan(1080);
    expect(first).toBeLessThan(1090);
    expect(Math.round(bearing(line[1], line[2]))).toBe(0);
    expect(project(line, cum, [12.9301, 77.625])).toBeCloseTo(first / 2, -1);
    const half = slice(line, cum, first / 2);
    expect(half).toHaveLength(2);
    expect(half[1][1]).toBeCloseTo(77.625, 4);
  });

  test("headings turn the short way round", () => {
    expect(lerpAngle(350, 10, 0.5)).toBeCloseTo(0);
    expect(lerpAngle(10, 350, 0.5)).toBeCloseTo(0);
  });
});

describe("cart", () => {
  const dosa = { id: "r1", slug: "dosa-camp", name: "Dosa Camp" };
  const momo = { id: "r2", slug: "momo-junction", name: "Momo Junction" };
  const item = (id: string, price: number) => ({ id, name: id, price_paise: price, is_veg: true, photo: null });

  test("adds, counts and totals one restaurant's food", () => {
    let cart: Cart | null = null;
    cart = add(cart, dosa, item("a", 14000)).cart;
    cart = add(cart, dosa, item("a", 14000)).cart;
    cart = add(cart, dosa, item("b", 4000)).cart;
    expect(count(cart)).toBe(3);
    expect(subtotal(cart)).toBe(32000);
    expect(qtyOf(cart, "a")).toBe(2);
    cart = setQty(cart!, "a", 0);
    expect(count(cart)).toBe(1);
    expect(drop(cart!, ["b"])).toBeNull();
  });

  test("another restaurant's dish is a conflict, not a mixed cart", () => {
    const cart = add(null, dosa, item("a", 14000)).cart;
    const res = add(cart, momo, item("m", 15000));
    expect(res.conflict).toBe(true);
    expect(res.cart).toBe(cart);
  });
});

describe("format", () => {
  test("money, distance, eta", () => {
    expect(inr(41400)).toBe("₹414");
    expect(inr(12345)).toBe("₹123.45");
    expect(km(640)).toBe("640 m");
    expect(km(2140)).toBe("2.1 km");
    expect(etaLabel(1320, "line")).toBe("≈ 22 min");
    expect(etaLabel(30, "osrm")).toBe("1 min");
  });
});

describe("the tracking reducer", () => {
  const order = {
    id: "o1",
    status: "placed",
    events: [{ order_id: "o1", status: "placed", at: "2026-11-26T15:00:00Z" }],
    timestamps: { placed: "2026-11-26T15:00:00Z" },
    legs: [],
    rider: null,
    rider_position: null,
    eta: null,
    reject_reason: null,
  } as unknown as OrderOut;
  const start: Live = { order, fix: null, fixAt: 0, eta: null, justChanged: null };

  test("status events light the rail once, even if replayed", () => {
    const ev = { order_id: "o1", status: "accepted" as const, at: "2026-11-26T15:01:00Z" };
    const once = liveReducer(start, { type: "status", data: ev });
    const twice = liveReducer(once, { type: "status", data: ev });
    expect(once.order.status).toBe("accepted");
    expect(twice).toBe(once);
    expect(twice.order.events.map((e) => e.status)).toEqual(["placed", "accepted"]);
  });

  test("a route event replaces the leg of the same kind; delivery clears the ETA", () => {
    const leg = { order_id: "o1", leg_id: "l1", kind: "to_customer", polyline: "", distance_m: 1, duration_s: 1, method: "osrm", started_at: "" } as const;
    let s = liveReducer(start, { type: "route", data: leg });
    s = liveReducer(s, { type: "route", data: { ...leg, leg_id: "l2" } });
    expect(s.order.legs.map((l) => l.leg_id)).toEqual(["l2"]);
    s = liveReducer(s, { type: "eta", data: { order_id: "o1", eta_s: 300, method: "osrm", phase: "to_customer" } });
    s = liveReducer(s, { type: "status", data: { order_id: "o1", status: "delivered", at: "2026-11-26T15:30:00Z" } });
    expect(s.eta).toBeNull();
  });
});

describe("safeNext", () => {
  test("keeps same-origin paths and refuses anything that leaves the site", () => {
    expect(safeNext("/orders/42?x=1#t")).toBe("/orders/42?x=1#t");
    for (const bad of [null, "", "https://evil.com", "//evil.com", "/\\evil.com", "/\\/evil.com", "\\\\evil.com", "/\t/evil.com"]) {
      expect(safeNext(bad)).toBeNull();
    }
  });
});
