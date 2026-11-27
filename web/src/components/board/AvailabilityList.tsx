"use client";

// S12 — menu availability (R8, v1: toggles only). A switched-off dish disappears from the customer
// menu and is refused by POST /orders. Toggles are optimistic; a failed PATCH reverts and says why.
import { useCallback, useEffect, useState } from "react";
import { RoleBar } from "@/components/ui/RoleBar";
import { api, errorMessage, type MenuItem, type MenuOut } from "@/lib/api";
import { inr } from "@/lib/format";
import { toast } from "@/lib/toast";
import { BoardTabs } from "./BoardTabs";
import "./board.css";

function setAvailable(menu: MenuOut, id: string, is_available: boolean): MenuOut {
  return {
    ...menu,
    categories: menu.categories.map((c) => ({
      ...c,
      items: c.items.map((it) => (it.id === id ? { ...it, is_available } : it)),
    })),
  };
}

export function AvailabilityList() {
  const [menu, setMenu] = useState<MenuOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [pending, setPending] = useState<ReadonlySet<string>>(() => new Set());

  const load = useCallback(async () => {
    setError(null);
    try {
      const m = await api<MenuOut>("/restaurant/menu");
      setMenu(m);
      setActive((a) => a ?? m.categories[0]?.id ?? null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(item: MenuItem) {
    if (pending.has(item.id)) return;
    const next = !item.is_available;
    setPending((s) => new Set(s).add(item.id));
    setMenu((m) => (m ? setAvailable(m, item.id, next) : m));
    try {
      const saved = await api<MenuItem>(`/restaurant/items/${item.id}`, {
        method: "PATCH",
        body: { is_available: next },
      });
      setMenu((m) => (m ? setAvailable(m, saved.id, saved.is_available) : m));
    } catch (err) {
      setMenu((m) => (m ? setAvailable(m, item.id, item.is_available) : m));
      toast(`Couldn't update ${item.name}`, errorMessage(err));
    } finally {
      setPending((s) => {
        const n = new Set(s);
        n.delete(item.id);
        return n;
      });
    }
  }

  function jump(id: string) {
    setActive(id);
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(`cat-${id}`)?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
  }

  const r = menu?.restaurant;

  return (
    <>
      <RoleBar
        title={r ? `${r.name} · menu` : "Menu"}
        subtitle={r ? `${r.area} · ${r.is_open ? (r.hours_label === "Open 24 hours" ? "Open 24 hours" : `Open · ${r.hours_label}`) : `Closed · ${r.hours_label}`}` : undefined}
        who="🍳 Kitchen"
      >
        <BoardTabs current="menu" />
      </RoleBar>

      {error && !menu && (
        <div className="tile peach spring" role="alert" style={{ marginTop: 10 }}>
          <h2>Couldn&apos;t load the menu</h2>
          <p className="muted" style={{ margin: "4px 0 12px" }}>
            {error}
          </p>
          <button type="button" className="btn" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}

      {!error && !menu && (
        <div className="av-grid" aria-busy="true" aria-label="Loading the menu">
          <div className="skeleton" style={{ height: 260 }} />
          <div className="skeleton" style={{ height: 420 }} />
        </div>
      )}

      {menu && (
        <div className="av-grid">
          <nav className="tile av-cats spring" aria-label="Categories">
            <span className="label">Categories</span>
            <ul>
              {menu.categories.map((c) => {
                const on = c.items.filter((i) => i.is_available).length;
                return (
                  <li key={c.id}>
                    <button type="button" aria-current={active === c.id ? "true" : undefined} onClick={() => jump(c.id)}>
                      <span>{c.name}</span>
                      <small className="num">
                        {on}/{c.items.length}
                      </small>
                    </button>
                  </li>
                );
              })}
            </ul>
            <p className="muted" style={{ fontSize: 12, margin: "12px 12px 4px" }}>
              Add / edit dishes — coming in v2
            </p>
          </nav>

          <div className="tile spring">
            <p className="chip lemon" style={{ whiteSpace: "normal", marginBottom: 14 }}>
              Switch a dish off and it disappears from the customer menu and can&apos;t be ordered.
            </p>
            {menu.categories.length === 0 && <p className="muted">No dishes on this menu yet.</p>}
            {menu.categories.map((c) => (
              <section key={c.id} className="av-section" aria-labelledby={`cat-${c.id}`}>
                <h2 id={`cat-${c.id}`}>{c.name}</h2>
                <ul className="av-items">
                  {c.items.map((it) => (
                    <li key={it.id} className={`av-item${it.is_available ? "" : " off"}`}>
                      {it.photo ? (
                        // eslint-disable-next-line @next/next/no-img-element -- small fixed thumbnails, no optimiser needed
                        <img src={it.photo.url} width={60} height={60} loading="lazy" alt="" />
                      ) : (
                        <span className="ph" aria-hidden="true">
                          🍽️
                        </span>
                      )}
                      <div className="txt">
                        <b>
                          <span className={`veg${it.is_veg ? "" : " non"}`} role="img" aria-label={it.is_veg ? "Veg" : "Non-veg"} />
                          {it.name}
                        </b>
                        <small className={it.is_available ? undefined : "so"}>
                          <span className="num">{inr(it.price_paise)}</span> · {it.is_available ? "available" : "sold out today"}
                        </small>
                      </div>
                      <button
                        type="button"
                        className="switch"
                        role="switch"
                        aria-checked={it.is_available}
                        aria-label={`${it.name} available`}
                        disabled={pending.has(it.id)}
                        onClick={() => void toggle(it)}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
