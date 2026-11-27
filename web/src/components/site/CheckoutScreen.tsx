"use client";

// S4: where to (a saved address or the pin), how to pay (cash, or Razorpay in test mode), the note,
// and the totals — always the API's quote, priced on the road distance. The order is priced again
// server-side when placed; nothing the browser says about money is trusted.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Map } from "@/components/map/Map";
import { api, ApiError, errorMessage, type Address, type OrderStart, type PaymentsConfig, type Quote, type RestaurantOut } from "@/lib/api";
import { drop, saveCart, useCart } from "@/lib/cart";
import { etaLabel, inr, km } from "@/lib/format";
import { usePin } from "@/lib/pin";
import { useMe } from "@/lib/session";
import { toast } from "@/lib/toast";

type Where = { key: string; label: string; line: string; lat: number; lng: number; editable?: boolean };

declare global {
  interface Window {
    Razorpay?: new (opts: Record<string, unknown>) => { open: () => void; on: (e: string, cb: () => void) => void };
  }
}

function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Couldn't load Razorpay"));
    document.body.appendChild(s);
  });
}

export function CheckoutScreen() {
  const me = useMe();
  const cart = useCart();
  const pin = usePin();
  const router = useRouter();
  const [addresses, setAddresses] = useState<Address[] | null>(null);
  const [where, setWhere] = useState<string>("pin");
  const [pinLine, setPinLine] = useState(pin.line);
  const [payment, setPayment] = useState<"cod" | "razorpay">("cod");
  const [config, setConfig] = useState<PaymentsConfig | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [problem, setProblem] = useState<ApiError | null>(null);
  const [placing, setPlacing] = useState(false);
  const [pending, setPending] = useState<OrderStart | null>(null);
  const [restaurant, setRestaurant] = useState<RestaurantOut | null>(null);

  useEffect(() => {
    if (me === null) router.replace("/sign-in?next=/checkout");
  }, [me, router]);

  useEffect(() => {
    if (!me) return;
    api<Address[]>("/addresses")
      .then((list) => {
        setAddresses(list);
        if (pin.addressId && list.some((a) => a.id === pin.addressId)) setWhere(pin.addressId);
      })
      .catch(() => setAddresses([]));
    api<PaymentsConfig>("/orders/config").then(setConfig).catch(() => setConfig({ razorpay_key_id: null }));
  }, [me, pin.addressId]);

  useEffect(() => {
    if (cart) api<RestaurantOut>(`/restaurants/${cart.restaurant.slug}`).then(setRestaurant).catch(() => undefined);
  }, [cart?.restaurant.slug]); // eslint-disable-line react-hooks/exhaustive-deps

  const options: Where[] = useMemo(
    () => [
      ...(addresses ?? []).map((a) => ({ key: a.id, label: a.label, line: a.line, lat: a.lat, lng: a.lng })),
      { key: "pin", label: pin.label, line: pinLine, lat: pin.lat, lng: pin.lng, editable: true },
    ],
    [addresses, pin, pinLine],
  );
  const chosen = options.find((o) => o.key === where) ?? options[options.length - 1];

  const body = useMemo(
    () =>
      cart && {
        restaurant_id: cart.restaurant.id,
        items: cart.lines.map((l) => ({ id: l.id, qty: l.qty })),
        address: { lat: chosen.lat, lng: chosen.lng },
      },
    [cart, chosen.lat, chosen.lng],
  );

  const refreshQuote = useCallback(async () => {
    if (!body || !me) return;
    setProblem(null);
    try {
      setQuote(await api<Quote>("/orders/quote", { body }));
    } catch (err) {
      setQuote(null);
      setProblem(err instanceof ApiError ? err : new ApiError(0, "error", errorMessage(err)));
    }
  }, [body, me]);

  useEffect(() => {
    void refreshQuote();
  }, [refreshQuote]);

  if (me === undefined) return <main id="main" className="page narrow"><div className="skeleton" style={{ height: 420 }} /></main>;
  if (!cart || cart.lines.length === 0) {
    return (
      <main id="main" className="page narrow">
        <div className="tile lemon spring">
          <h1 style={{ fontSize: 22 }}>Your cart is empty</h1>
          <p className="muted" style={{ marginTop: 4 }}>Pick a kitchen near you and add a dish or two.</p>
          <Link className="btn" href="/" style={{ marginTop: 12 }}>Browse kitchens</Link>
        </div>
      </main>
    );
  }

  const unavailableIds = problem?.code === "item_unavailable" ? ((problem.details.ids as string[]) ?? []) : [];
  const line = chosen.editable ? pinLine.trim() : chosen.line;

  const payRazorpay = async (start: OrderStart) => {
    if (!start.razorpay) return;
    try {
      await loadRazorpay();
    } catch {
      toast("Couldn't open Razorpay", "Check your connection, or switch to cash on delivery.");
      return;
    }
    const rz = start.razorpay;
    const modal = new window.Razorpay!({
      key: rz.key_id,
      amount: rz.amount_paise,
      currency: "INR",
      order_id: rz.order_id,
      name: rz.name,
      description: rz.description,
      prefill: rz.prefill,
      theme: { color: "#7B5CFF" },
      handler: async (resp: { razorpay_payment_id: string; razorpay_signature: string }) => {
        try {
          await api(`/orders/${start.order.id}/verify`, { body: resp });
          saveCart(null);
          router.push(`/orders/${start.order.id}`);
        } catch (err) {
          toast("Payment not confirmed", errorMessage(err));
        }
      },
      modal: {
        ondismiss: () => {
          setPending(start);
          toast("Payment window closed", "Your order is saved for 15 minutes. Try again or pay cash.");
        },
      },
    });
    modal.open();
  };

  const place = async () => {
    if (!body || !quote || line.length < 3) return;
    setPlacing(true);
    try {
      const start = await api<OrderStart>("/orders", {
        body: { ...body, address_line: line, payment, note: cart.note || undefined, expected_total_paise: quote.total_paise },
      });
      if (payment === "cod") {
        saveCart(null);
        router.push(`/orders/${start.order.id}`);
        return;
      }
      await payRazorpay(start);
    } catch (err) {
      if (err instanceof ApiError && err.code === "price_changed") {
        setQuote(err.details.quote as Quote);
        toast("The total changed", "Delivery is priced on the road distance. Check the new total, then place the order again.");
      } else {
        toast("Couldn't place the order", errorMessage(err));
        void refreshQuote();
      }
    } finally {
      setPlacing(false);
    }
  };

  return (
    <main id="main" className="page narrow checkout-page">
      <div className="checkout">
        <h1 className="span2" style={{ fontSize: 24, margin: "4px 4px 0" }}>Checkout</h1>

        {pending && (
          <div className="tile sky span2 spring">
            <b>Payment window closed</b>
            <p style={{ fontSize: 13 }}>{pending.order.number} is saved for 15 minutes. Finish paying, or switch to cash on delivery.</p>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn small" onClick={() => payRazorpay(pending)}>Pay now</button>
              <button className="btn small ghost" onClick={() => { setPending(null); setPayment("cod"); }}>Pay cash instead</button>
            </div>
          </div>
        )}

        <section className="tile span2 spring" aria-labelledby="where-h">
          <h2 id="where-h" className="label" style={{ marginBottom: 8 }}>Deliver to</h2>
          <div className="stack" role="radiogroup" aria-label="Delivery address">
            {options.map((o) => (
              <button key={o.key} role="radio" aria-checked={where === o.key} className={`addr-opt ${where === o.key ? "on" : ""}`} onClick={() => setWhere(o.key)}>
                <b>{o.label}</b>
                <span>{o.editable ? "the pin on the map" : o.line}</span>
              </button>
            ))}
          </div>
          {chosen.editable && (
            <label className="field" style={{ marginTop: 10 }}>
              <span className="label">Flat, street, landmark</span>
              <input className="input" value={pinLine} onChange={(e) => setPinLine(e.target.value)} placeholder="e.g. 3rd floor, 17th Cross" />
            </label>
          )}
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            Wrong spot? <Link href="/">Move the pin</Link> or <Link href="/addresses">manage addresses</Link>.
          </p>
          <div className="mini-map">
            <Map
              label="Delivery address on the map"
              center={[chosen.lat, chosen.lng]}
              zoom={14}
              interactive={false}
              fit={restaurant ? [[restaurant.lat, restaurant.lng], [chosen.lat, chosen.lng]] : [[chosen.lat, chosen.lng]]}
              fitKey={`${chosen.lat},${chosen.lng},${restaurant?.id}`}
              markers={[
                { id: "drop", kind: "drop", lat: chosen.lat, lng: chosen.lng, title: "Delivery address" },
                ...(restaurant ? [{ id: "rest", kind: "restaurant" as const, lat: restaurant.lat, lng: restaurant.lng, title: restaurant.name }] : []),
              ]}
            />
          </div>
        </section>

        <button className={`tile mint pay ${payment === "cod" ? "on" : ""}`} role="radio" aria-checked={payment === "cod"} onClick={() => setPayment("cod")}>
          <span aria-hidden="true">💵</span>
          Cash on delivery
          <small>pay the rider</small>
        </button>
        <button
          className={`tile sky pay ${payment === "razorpay" ? "on" : ""}`}
          role="radio"
          aria-checked={payment === "razorpay"}
          disabled={!config?.razorpay_key_id}
          onClick={() => setPayment("razorpay")}
        >
          <span aria-hidden="true">💳</span>
          Razorpay
          <small>{config === null ? "…" : config.razorpay_key_id ? "UPI · cards · test mode" : "switched off in this demo"}</small>
        </button>

        <section className="tile totals span2 spring" aria-labelledby="bill-h" aria-busy={!quote && !problem}>
          <h2 id="bill-h" className="label" style={{ marginBottom: 6 }}>{cart.restaurant.name}</h2>
          {cart.lines.map((l) => (
            <div key={l.id} style={{ color: unavailableIds.includes(l.id) ? "var(--coral-deep)" : undefined }}>
              <span>
                {l.qty} × {l.name}
                {unavailableIds.includes(l.id) && " (sold out)"}
              </span>
              <span className="num">{inr(l.qty * l.price_paise)}</span>
            </div>
          ))}
          {quote ? (
            <>
              <div>
                <span>Delivery · {km(quote.distance_m)} {quote.method === "line" ? "(estimated)" : "by road"}</span>
                <span className="num">{inr(quote.delivery_fee_paise)}</span>
              </div>
              <div><span>Platform fee</span><span className="num">{inr(quote.platform_fee_paise)}</span></div>
              <div className="t"><span>Total</span><span className="num">{inr(quote.total_paise)}</span></div>
              <p className="muted" style={{ fontSize: 12, marginTop: 4 }}>₹25 up to 2 km, then ₹8 per started km. Arrives in about {etaLabel(quote.eta_s, quote.method)}.</p>
            </>
          ) : problem ? (
            <div className="tile peach" style={{ marginTop: 8 }}>
              <b>{problem.message}</b>
              {problem.code === "item_unavailable" && (
                <button className="btn small" style={{ marginTop: 8 }} onClick={() => saveCart(drop(cart, unavailableIds))}>
                  Remove sold-out items
                </button>
              )}
              {problem.code === "out_of_range" && <p style={{ fontSize: 13 }}>Pick an address within 5 km of the kitchen.</p>}
              {problem.code === "restaurant_closed" && <p style={{ fontSize: 13 }}>{String(problem.details.opens ?? "")}</p>}
            </div>
          ) : (
            <div className="skeleton" style={{ height: 70, marginTop: 8 }} />
          )}
        </section>

        <label className="tile span2" style={{ display: "grid", gap: 6 }}>
          <span className="label">Note to the kitchen</span>
          <textarea className="input" maxLength={280} placeholder="Extra chutney, less spicy…" value={cart.note} onChange={(e) => saveCart({ ...cart, note: e.target.value })} />
        </label>
      </div>

      <button className="cartbar" onClick={place} disabled={!quote || placing || line.length < 3} style={{ opacity: !quote || line.length < 3 ? 0.7 : 1 }}>
        <span className="num">{quote ? `${inr(quote.total_paise)} · ETA ${etaLabel(quote.eta_s, quote.method)}` : "Pricing…"}</span>
        <span className="go" style={{ background: "var(--green)", color: "var(--ink)" }}>
          {placing ? "Placing…" : line.length < 3 ? "Add the street first" : payment === "cod" ? "Place order →" : "Pay & place →"}
        </span>
      </button>
    </main>
  );
}
