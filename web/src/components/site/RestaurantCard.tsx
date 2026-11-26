import Image from "next/image";
import Link from "next/link";
import type { RestaurantCard as Card } from "@/lib/api";
import { etaLabel, inr, km } from "@/lib/format";

export function RestaurantCard({ r, big }: { r: Card; big?: boolean }) {
  const off = !r.orderable;
  const badge = r.reason === "too_far" ? `Too far · ${km(r.distance_m)}` : r.reason === "closed" ? r.opens ?? "Closed now" : etaLabel(r.eta_s);
  return (
    <Link
      href={`/r/${r.slug}`}
      className="tile flush spring rcard"
      style={{ position: "relative", display: "block", textDecoration: "none", gridColumn: big ? "1 / -1" : undefined, opacity: off ? 0.7 : 1, aspectRatio: big ? "5 / 2" : "4 / 3.4" }}
    >
      {r.cover && (
        <Image
          src={r.cover.url}
          alt=""
          width={r.cover.width}
          height={r.cover.height}
          sizes="(max-width: 760px) 50vw, 33vw"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", filter: off ? "grayscale(.7)" : undefined }}
        />
      )}
      <span className={`chip ${off ? "peach" : "dark"}`} style={{ position: "absolute", top: 10, left: 10 }}>
        {badge}
      </span>
      {r.rating && (
        <span className="chip white" style={{ position: "absolute", top: 10, right: 10 }}>
          ★ {r.rating.toFixed(1)}
        </span>
      )}
      <span
        style={{ position: "absolute", left: 10, right: 10, bottom: 10, background: "#fff", borderRadius: 14, padding: "7px 11px", boxShadow: "var(--shadow-pop)", display: "grid" }}
      >
        <b style={{ fontWeight: 900, fontSize: 14 }}>
          {r.is_veg && <span role="img" className="veg" style={{ marginRight: 6, verticalAlign: -1 }} aria-label="Pure veg" />}
          {r.name}
        </b>
        <small style={{ fontWeight: 700, fontSize: 11, color: "var(--ink2)" }}>
          {r.cuisines.slice(0, 2).join(" · ")} · {km(r.distance_m)}
          {r.orderable ? ` · ${inr(r.delivery_fee_paise)} delivery` : ""}
        </small>
      </span>
    </Link>
  );
}
