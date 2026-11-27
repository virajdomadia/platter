"use client";

// S2 + S3: cover, info strip for the current pin, the menu by category (veg marks, sold-out dishes
// greyed and not addable), and the cart — a bar that bumps when a dish photo slides into it
// ("Plate slide"), and a sheet with quantities, a note and the totals preview.
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, errorMessage, type Me, type MenuItem, type RestaurantCard, type RestaurantOut } from "@/lib/api";
import { add, count, qtyOf, saveCart, setQty, subtotal, useCart, type Cart } from "@/lib/cart";
import { etaLabel, inr, km } from "@/lib/format";
import { usePin } from "@/lib/pin";
import { setMe, useMe } from "@/lib/session";
import { toast } from "@/lib/toast";

const reduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function RestaurantScreen({ restaurant: r }: { restaurant: RestaurantOut }) {
  const pin = usePin();
  const cart = useCart();
  const router = useRouter();
  const [card, setCard] = useState<RestaurantOut>(r);
  const [conflict, setConflict] = useState<MenuItem | null>(null);
  const [sheet, setSheet] = useState(false);
  const [bump, setBump] = useState(0);
  const bar = useRef<HTMLButtonElement>(null);
  const owner = { id: r.id, slug: r.slug, name: r.name };
  const mine = cart && cart.restaurant.id === r.id ? cart : null;

  useEffect(() => {
    api<RestaurantOut>(`/restaurants/${r.slug}?lat=${pin.lat}&lng=${pin.lng}`)
      .then((fresh) => setCard(fresh))
      .catch(() => undefined);
  }, [r.slug, pin.lat, pin.lng]);

  const plateSlide = (img: HTMLElement | null) => {
    setBump((n) => n + 1);
    if (!img || reduced()) return;
    const from = img.getBoundingClientRect();
    const target = bar.current?.getBoundingClientRect() ?? { left: window.innerWidth / 2 - 30, top: window.innerHeight - 70, width: 60, height: 50 };
    const ghost = img.cloneNode(true) as HTMLImageElement;
    ghost.className = "flying-plate";
    Object.assign(ghost.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px` });
    document.body.appendChild(ghost);
    requestAnimationFrame(() => {
      const dx = target.left + 30 - from.left;
      const dy = target.top + 6 - from.top;
      ghost.style.transform = `translate(${dx}px, ${dy}px) scale(0.25)`;
      ghost.style.opacity = "0.2";
    });
    window.setTimeout(() => ghost.remove(), 600);
  };

  const addItem = (item: MenuItem, img: HTMLElement | null) => {
    const res = add(cart, owner, { id: item.id, name: item.name, price_paise: item.price_paise, is_veg: item.is_veg, photo: item.photo?.url ?? null });
    if (res.conflict) return setConflict(item);
    saveCart(res.cart);
    plateSlide(img);
  };

  const unavailable = !card.orderable;

  return (
    <main id="main" className="page menu-page">
      <Link href="/" className="back-link">
        <span aria-hidden="true">← </span>All kitchens
      </Link>
      <section className="menu-hero">
        <div className="tile flush cover spring">
          {r.cover && <Image src={r.cover.url} alt="" width={r.cover.width} height={r.cover.height} priority sizes="(max-width: 760px) 50vw, 400px" />}
        </div>
        <div className="tile lav spring">
          <h1 style={{ fontSize: 26 }}>
            {r.is_veg && <span role="img" className="veg" style={{ marginRight: 8, verticalAlign: 3 }} aria-label="Pure veg" />}
            {r.name}
          </h1>
          <p style={{ fontSize: 13, color: "var(--ink2)", marginTop: 4 }}>
            {r.cuisines.join(" · ")} · {r.area}
          </p>
          <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>{r.address}</p>
        </div>
        <div className="tile spring strip">
          {r.rating && <span className="chip">★ {r.rating.toFixed(1)}</span>}
          <span className="chip">{etaLabel(card.eta_s)}</span>
          <span className="chip">{km(card.distance_m)} from {pin.label}</span>
          {card.orderable && <span className="chip">{inr(card.delivery_fee_paise)} delivery</span>}
          <span className="chip">{r.hours_label}</span>
        </div>
      </section>

      {unavailable && (
        <div className="tile peach spring" style={{ marginBottom: 10 }}>
          <b>{card.reason === "too_far" ? `${r.name} can't reach ${pin.label}` : `${r.name} is closed right now`}</b>
          <p style={{ fontSize: 13 }}>
            {card.reason === "too_far"
              ? `It's ${km(card.distance_m)} away and we deliver within 5 km. `
              : `${card.opens ?? "It opens again soon"}. `}
            <Link href="/">See kitchens that can deliver now →</Link>
          </p>
        </div>
      )}

      <nav className="cat-chips" aria-label="Menu sections">
        {card.categories.map((c) => (
          <a key={c.id} className="chip white" href={`#cat-${c.id}`}>
            {c.name}
          </a>
        ))}
      </nav>

      {card.categories.map((c) => (
        <section key={c.id} id={`cat-${c.id}`} aria-labelledby={`h-${c.id}`} style={{ scrollMarginTop: 90 }}>
          <h2 id={`h-${c.id}`} style={{ fontSize: 17, margin: "16px 4px 8px" }}>
            {c.name}
          </h2>
          <div className="menu-grid">
            {c.items.map((item) => (
              <DishRow key={item.id} item={item} qty={qtyOf(mine, item.id)} disabled={unavailable} onAdd={addItem} onQty={(q) => mine && saveCart(setQty(mine, item.id, q))} />
            ))}
          </div>
        </section>
      ))}

      {mine && count(mine) > 0 && (
        <button ref={bar} key={bump} className={`cartbar ${bump ? "bump" : ""}`} onClick={() => setSheet(true)} aria-label={`Cart: ${count(mine)} items, ${inr(subtotal(mine))}. Open cart`}>
          <span className="num">
            {count(mine)} {count(mine) === 1 ? "item" : "items"} · {inr(subtotal(mine))}
          </span>
          <span className="go">View cart →</span>
        </button>
      )}

      {sheet && mine && <CartSheet cart={mine} card={card} onClose={() => setSheet(false)} onCheckout={() => router.push("/checkout")} />}

      {conflict && (
        <>
          <div className="sheet-dim" onClick={() => setConflict(null)} />
          <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="switch-h">
            <div className="tile lemon">
              <h2 id="switch-h" style={{ fontSize: 18 }}>Start a new cart?</h2>
              <p style={{ fontSize: 14, marginTop: 4 }}>
                Your cart has {count(cart)} {count(cart) === 1 ? "item" : "items"} from {cart?.restaurant.name}. One restaurant per order.
              </p>
            </div>
            <div className="grid2" style={{ marginTop: 10 }}>
              <button className="btn ghost" onClick={() => setConflict(null)} autoFocus>
                Keep my cart
              </button>
              <button
                className="btn"
                onClick={() => {
                  const res = add(null, owner, { id: conflict.id, name: conflict.name, price_paise: conflict.price_paise, is_veg: conflict.is_veg, photo: conflict.photo?.url ?? null });
                  saveCart(res.cart);
                  setConflict(null);
                  setBump((n) => n + 1);
                }}
              >
                Clear &amp; add
              </button>
            </div>
          </div>
        </>
      )}
    </main>
  );
}

function DishRow({
  item,
  qty,
  disabled,
  onAdd,
  onQty,
}: {
  item: MenuItem;
  qty: number;
  disabled: boolean;
  onAdd: (item: MenuItem, img: HTMLElement | null) => void;
  onQty: (q: number) => void;
}) {
  const img = useRef<HTMLImageElement>(null);
  const soldOut = !item.is_available;
  return (
    <div className="tile dish spring" style={{ opacity: soldOut ? 0.55 : 1 }}>
      {item.photo ? (
        <Image ref={img} src={item.photo.url} alt="" width={item.photo.width} height={item.photo.height} sizes="84px" loading="lazy" />
      ) : (
        <span className="dish-ph" aria-hidden="true">🍽️</span>
      )}
      <div style={{ minWidth: 0 }}>
        <b>
          <span role="img" className={`veg ${item.is_veg ? "" : "non"}`} aria-label={item.is_veg ? "Veg" : "Non-veg"} /> {item.name}
        </b>
        {item.description && <p>{item.description}</p>}
        <span className="num" style={{ fontWeight: 900 }}>{inr(item.price_paise)}</span>
        {soldOut && <span className="chip peach" style={{ marginLeft: 8 }}>Sold out today</span>}
      </div>
      {soldOut || disabled ? null : qty > 0 ? (
        <div className="stepper" role="group" aria-label={`${item.name} quantity`}>
          <button onClick={() => onQty(qty - 1)} aria-label={`One less ${item.name}`}>−</button>
          <span className="num" aria-live="polite">{qty}</span>
          <button onClick={() => (qty < 20 ? onAdd(item, img.current) : undefined)} aria-label={`One more ${item.name}`}>+</button>
        </div>
      ) : (
        <button className="add" onClick={() => onAdd(item, img.current)} aria-label={`Add ${item.name}`}>
          +
        </button>
      )}
    </div>
  );
}

/** A guest skips the sign-in page: one tap signs in as the demo customer and goes to checkout. */
function DemoCheckout() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="btn ghost"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          setMe(await api<Me>("/auth/demo", { body: { as: "customer" } }));
          router.push("/checkout");
        } catch (err) {
          toast("Couldn't sign in", errorMessage(err));
          setBusy(false);
        }
      }}
    >
      {busy ? "Signing in…" : "Continue as the demo customer"}
    </button>
  );
}

function CartSheet({ cart, card, onClose, onCheckout }: { cart: Cart; card: RestaurantCard; onClose: () => void; onCheckout: () => void }) {
  const sub = subtotal(cart);
  const me = useMe();
  const [sure, setSure] = useState(false); // emptying takes two taps: one mis-tap can't lose the cart
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <>
      <div className="sheet-dim" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="cart-h">
        <div className="between" style={{ margin: "0 4px 10px" }}>
          <h2 id="cart-h" style={{ fontSize: 18 }}>Your cart · {cart.restaurant.name}</h2>
          <button className="chip white" onClick={onClose} aria-label="Close cart">✕</button>
        </div>
        <div className="stack">
          {cart.lines.map((l) => (
            <div key={l.id} className="tile dish" style={{ padding: 8 }}>
              {l.photo ? <Image src={l.photo} alt="" width={480} height={360} sizes="56px" style={{ width: 56, height: 56 }} /> : <span className="dish-ph" aria-hidden="true">🍽️</span>}
              <div>
                <b>{l.name}</b>
                <p>{inr(l.price_paise)} each</p>
              </div>
              <div className="stepper" role="group" aria-label={`${l.name} quantity`}>
                <button onClick={() => saveCart(setQty(cart, l.id, l.qty - 1))} aria-label={`One less ${l.name}`}>−</button>
                <span className="num">{l.qty}</span>
                <button onClick={() => saveCart(setQty(cart, l.id, l.qty + 1))} aria-label={`One more ${l.name}`} disabled={l.qty >= 20}>+</button>
              </div>
            </div>
          ))}
          <label className="tile" style={{ display: "grid", gap: 6 }}>
            <span className="label">Note to the kitchen</span>
            <textarea
              className="input"
              maxLength={280}
              placeholder="Extra chutney, less spicy…"
              value={cart.note}
              onChange={(e) => saveCart({ ...cart, note: e.target.value })}
            />
          </label>
          <div className="tile totals">
            <div><span>Items</span><span className="num">{inr(sub)}</span></div>
            <div><span>Delivery · about {km(card.distance_m * 1.3)}</span><span className="num">≈ {inr(card.delivery_fee_paise)}</span></div>
            <div><span>Platform fee</span><span className="num">₹5</span></div>
            <div className="t"><span>Estimated total</span><span className="num">≈ {inr(sub + card.delivery_fee_paise + 500)}</span></div>
            <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>Checkout prices the delivery on the road distance to your address.</p>
          </div>
          <div className="grid2">
            <button
              className={`btn ${sure ? "" : "ghost"}`}
              style={sure ? { background: "var(--coral-deep)" } : undefined}
              onClick={() => {
                if (!sure) return setSure(true);
                saveCart(null);
                onClose();
              }}
              onBlur={() => setSure(false)}
            >
              {sure ? "Tap again to empty" : "Empty cart"}
            </button>
            <button className="btn" onClick={onCheckout} disabled={!card.orderable}>Checkout →</button>
          </div>
          {me === null && card.orderable && <DemoCheckout />}
        </div>
      </div>
    </>
  );
}
