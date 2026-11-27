"use client";

// S12 — the menu editor (v2 L3). Categories (add, rename, reorder, delete when empty), dishes (add,
// edit, delete, availability), and restaurant details (open switch, prep time, cover, hours). Every
// save answers with the whole menu, so the screen is always what the server holds. The public demo
// kitchen edits a private copy (`menu.sandbox`): customers keep seeing the live menu.
import { useCallback, useEffect, useRef, useState } from "react";
import { RoleBar } from "@/components/ui/RoleBar";
import { api, errorMessage, type MenuItem, type MenuOut } from "@/lib/api";
import { inr } from "@/lib/format";
import { toast } from "@/lib/toast";
import { BoardTabs } from "./BoardTabs";
import "./board.css";

type Draft = {
  id: string | null;
  category_id: string;
  name: string;
  description: string;
  rupees: string;
  is_veg: boolean;
  photo_url: string | null;
  is_available: boolean;
};

const DAYS = [
  ["mon", "Monday"],
  ["tue", "Tuesday"],
  ["wed", "Wednesday"],
  ["thu", "Thursday"],
  ["fri", "Friday"],
  ["sat", "Saturday"],
  ["sun", "Sunday"],
] as const;

function setAvailable(menu: MenuOut, id: string, is_available: boolean): MenuOut {
  return {
    ...menu,
    categories: menu.categories.map((c) => ({
      ...c,
      items: c.items.map((it) => (it.id === id ? { ...it, is_available } : it)),
    })),
  };
}

function photoName(url: string): string {
  const base = url.split("/").pop()?.replace(/\.\w+$/, "").replace(/-/g, " ") ?? "photo";
  return base.charAt(0).toUpperCase() + base.slice(1);
}

export function MenuEditor() {
  const [menu, setMenu] = useState<MenuOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [pending, setPending] = useState<ReadonlySet<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [photos, setPhotos] = useState<string[] | null>(null);
  const [arranging, setArranging] = useState(false);

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

  const needPhotos = useCallback(() => {
    if (photos) return;
    api<string[]>("/restaurant/photos")
      .then(setPhotos)
      .catch(() => setPhotos([]));
  }, [photos]);

  /** Run a save that answers with the whole menu; say what went wrong if it fails. */
  async function save(what: string, call: () => Promise<MenuOut>): Promise<boolean> {
    setBusy(true);
    try {
      setMenu(await call());
      return true;
    } catch (err) {
      toast(`Couldn't ${what}`, errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function toggle(item: MenuItem) {
    if (pending.has(item.id)) return;
    const next = !item.is_available;
    setPending((s) => new Set(s).add(item.id));
    setMenu((m) => (m ? setAvailable(m, item.id, next) : m));
    try {
      const saved = await api<MenuItem>(`/restaurant/items/${item.id}`, { method: "PATCH", body: { is_available: next } });
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

  function openDish(categoryId: string, item?: MenuItem) {
    needPhotos();
    setDraft({
      id: item?.id ?? null,
      category_id: categoryId,
      name: item?.name ?? "",
      description: item?.description ?? "",
      rupees: item ? String(item.price_paise / 100) : "",
      is_veg: item?.is_veg ?? true,
      photo_url: item?.photo?.url ?? null,
      is_available: item?.is_available ?? true,
    });
  }

  const r = menu?.restaurant;
  const cats = menu?.categories ?? [];

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

      {menu && menu.sandbox && (
        <p className="tile lemon me-note" role="note">
          Demo kitchen: your edits stay in this demo and reset at the next demo sign-in. Customers keep seeing the live menu.
        </p>
      )}

      {menu && menu.details && <Details menu={menu} busy={busy} save={save} needPhotos={needPhotos} photos={photos} />}

      {menu && (
        <div className="av-grid">
          <nav className="tile av-cats spring" aria-label="Categories">
            <div className="between">
              <span className="label">Categories</span>
              <button type="button" className="btn small ghost me-arrange" aria-pressed={arranging} onClick={() => setArranging((a) => !a)}>
                {arranging ? "Done" : "Edit categories"}
              </button>
            </div>
            <ul>
              {cats.map((c, i) => (
                <CategoryRow
                  key={c.id}
                  name={c.name}
                  count={`${c.items.filter((x) => x.is_available).length}/${c.items.length}`}
                  current={active === c.id}
                  empty={c.items.length === 0}
                  first={i === 0}
                  last={i === cats.length - 1}
                  busy={busy}
                  arranging={arranging}
                  onJump={() => jump(c.id)}
                  onMove={(d) => {
                    const ids = cats.map((x) => x.id);
                    [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
                    void save("reorder", () => api<MenuOut>("/restaurant/categories/order", { method: "PUT", body: { ids } }));
                  }}
                  onRename={(name) => save("rename the category", () => api<MenuOut>(`/restaurant/categories/${c.id}`, { method: "PATCH", body: { name } }))}
                  onDelete={() => void save("delete the category", () => api<MenuOut>(`/restaurant/categories/${c.id}`, { method: "DELETE" }))}
                />
              ))}
            </ul>
            {arranging && <AddCategory busy={busy} onAdd={(name) => save("add the category", () => api<MenuOut>("/restaurant/categories", { body: { name } }))} />}
          </nav>

          <div className="tile spring">
            <p className="chip lemon" style={{ whiteSpace: "normal", marginBottom: 14 }}>
              Switch a dish off and it disappears from the customer menu and can&apos;t be ordered.
            </p>
            {cats.length === 0 && <p className="muted">No categories yet. Add one to start the menu.</p>}
            {cats.map((c) => (
              <section key={c.id} className="av-section" aria-labelledby={`cat-${c.id}`}>
                <div className="me-head">
                  <h2 id={`cat-${c.id}`}>{c.name}</h2>
                  <button type="button" className="btn small" onClick={() => openDish(c.id)} disabled={busy}>
                    Add dish<span className="sr-only"> to {c.name}</span>
                  </button>
                </div>
                {c.items.length === 0 && <p className="muted">No dishes here yet.</p>}
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
                      <button type="button" className="btn small ghost me-edit" onClick={() => openDish(c.id, it)} disabled={busy}>
                        Edit<span className="sr-only"> {it.name}</span>
                      </button>
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

      {draft && menu && (
        <DishDialog
          draft={draft}
          setDraft={setDraft}
          categories={cats}
          photos={photos}
          busy={busy}
          onClose={() => setDraft(null)}
          onSave={async () => {
            const body = {
              category_id: draft.category_id,
              name: draft.name.trim(),
              description: draft.description.trim() || null,
              price_paise: Math.round(Number(draft.rupees) * 100),
              is_veg: draft.is_veg,
              photo_url: draft.photo_url,
              is_available: draft.is_available,
            };
            const ok = draft.id
              ? await save("save the dish", async () => {
                  await api(`/restaurant/items/${draft.id}`, { method: "PATCH", body });
                  return api<MenuOut>("/restaurant/menu");
                })
              : await save("add the dish", () => api<MenuOut>("/restaurant/items", { body }));
            if (ok) toast(draft.id ? "Dish saved" : "Dish added", body.name, "ok");
            return ok;
          }}
          onDelete={
            draft.id
              ? () => save("delete the dish", () => api<MenuOut>(`/restaurant/items/${draft.id}`, { method: "DELETE" }))
              : undefined
          }
        />
      )}
    </>
  );
}

// ── categories ──────────────────────────────────────────────────────────────────────────────

function CategoryRow(p: {
  name: string;
  count: string;
  current: boolean;
  empty: boolean;
  first: boolean;
  last: boolean;
  busy: boolean;
  arranging: boolean;
  onJump: () => void;
  onMove: (d: -1 | 1) => void;
  onRename: (name: string) => Promise<boolean>;
  onDelete: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(p.name);
  if (renaming) {
    return (
      <li>
        <form
          className="me-rename"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await p.onRename(name.trim())) setRenaming(false);
          }}
        >
          <label className="sr-only" htmlFor={`rn-${p.name}`}>
            New name for {p.name}
          </label>
          <input id={`rn-${p.name}`} className="input" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <button className="btn small" disabled={p.busy}>
            Save
          </button>
          <button type="button" className="btn small ghost" onClick={() => setRenaming(false)}>
            Cancel
          </button>
        </form>
      </li>
    );
  }
  return (
    <li className="me-cat">
      <button type="button" aria-current={p.current ? "true" : undefined} onClick={p.onJump}>
        <span>{p.name}</span>
        <small className="num">{p.count}</small>
      </button>
      {p.arranging && (
        <div className="me-tools" role="group" aria-label={`${p.name} tools`}>
          <button type="button" disabled={p.first || p.busy} onClick={() => p.onMove(-1)} aria-label={`Move ${p.name} up`}>
            ↑
          </button>
          <button type="button" disabled={p.last || p.busy} onClick={() => p.onMove(1)} aria-label={`Move ${p.name} down`}>
            ↓
          </button>
          <button type="button" disabled={p.busy} onClick={() => setRenaming(true)} aria-label={`Rename ${p.name}`}>
            Rename
          </button>
          <button
            type="button"
            disabled={!p.empty || p.busy}
            onClick={() => window.confirm(`Delete the empty category ${p.name}?`) && p.onDelete()}
            aria-label={p.empty ? `Delete ${p.name}` : `Delete ${p.name} (move or delete its dishes first)`}
            title={p.empty ? undefined : "Move or delete its dishes first"}
          >
            Delete
          </button>
        </div>
      )}
    </li>
  );
}

function AddCategory({ busy, onAdd }: { busy: boolean; onAdd: (name: string) => Promise<boolean> }) {
  const [name, setName] = useState("");
  return (
    <form
      className="me-add"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await onAdd(name.trim())) setName("");
      }}
    >
      <label className="field">
        <span className="label">New category</span>
        <input className="input" required maxLength={60} placeholder="Chef's specials" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <button className="btn small" disabled={busy || !name.trim()}>
        Add category
      </button>
    </form>
  );
}

// ── one dish ────────────────────────────────────────────────────────────────────────────────

function DishDialog(p: {
  draft: Draft;
  setDraft: (d: Draft | null) => void;
  categories: MenuOut["categories"];
  photos: string[] | null;
  busy: boolean;
  onClose: () => void;
  onSave: () => Promise<boolean>;
  onDelete?: () => Promise<boolean>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const d = p.draft;
  const set = (patch: Partial<Draft>) => p.setDraft({ ...d, ...patch });
  useEffect(() => {
    const dlg = ref.current;
    if (dlg && !dlg.open) dlg.showModal(); // native modal: focus trap, Esc, inert page behind
  }, []);
  const price = Number(d.rupees);
  const priceOk = d.rupees !== "" && Number.isFinite(price) && price >= 1 && price <= 10000;

  return (
    <dialog ref={ref} className="me-dialog" aria-labelledby="dish-h" onClose={p.onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          // Closing the native dialog hands focus back to the button that opened it.
          if (priceOk) void p.onSave().then((ok) => ok && ref.current?.close());
        }}
      >
        <h2 id="dish-h">{d.id ? `Edit ${d.name || "dish"}` : "Add a dish"}</h2>
        <div className="me-form">
          <label className="field">
            <span className="label">Name</span>
            <input className="input" required maxLength={80} value={d.name} onChange={(e) => set({ name: e.target.value })} />
          </label>
          <label className="field">
            <span className="label">Price (₹)</span>
            <input
              className="input num"
              required
              inputMode="decimal"
              type="number"
              min={1}
              max={10000}
              step="0.5"
              value={d.rupees}
              aria-describedby="price-help"
              aria-invalid={d.rupees !== "" && !priceOk}
              onChange={(e) => set({ rupees: e.target.value })}
            />
            <small id="price-help" className={d.rupees !== "" && !priceOk ? "error-text" : "muted"}>
              From ₹1 to ₹10,000
            </small>
          </label>
          <label className="field me-wide">
            <span className="label">Description (optional)</span>
            <textarea className="input" maxLength={280} value={d.description} onChange={(e) => set({ description: e.target.value })} />
          </label>
          <label className="field">
            <span className="label">Category</span>
            <select className="input" value={d.category_id} onChange={(e) => set({ category_id: e.target.value })}>
              {p.categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="field me-checks">
            <legend className="label">Dish</legend>
            <label>
              <input type="checkbox" checked={d.is_veg} onChange={(e) => set({ is_veg: e.target.checked })} /> Vegetarian
            </label>
            <label>
              <input type="checkbox" checked={d.is_available} onChange={(e) => set({ is_available: e.target.checked })} /> Available now
            </label>
          </fieldset>
          <PhotoPicker legend="Photo" photos={p.photos} value={d.photo_url} onChange={(photo_url) => set({ photo_url })} allowNone />
        </div>
        <div className="me-actions">
          {p.onDelete && (
            <button
              type="button"
              className="btn small ghost me-danger"
              disabled={p.busy}
              onClick={() => {
                if (window.confirm(`Delete ${d.name}? Past orders keep their copy.`)) void p.onDelete?.().then((ok) => ok && ref.current?.close());
              }}
            >
              Delete dish
            </button>
          )}
          <span style={{ flex: 1 }} />
          <button type="button" className="btn small ghost" onClick={() => ref.current?.close()}>
            Cancel
          </button>
          <button className="btn small" disabled={p.busy || !priceOk || !d.name.trim()}>
            {p.busy ? "Saving…" : d.id ? "Save dish" : "Add dish"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function PhotoPicker(p: {
  legend: string;
  photos: string[] | null;
  value: string | null;
  onChange: (url: string | null) => void;
  allowNone?: boolean;
}) {
  return (
    <fieldset className="field me-wide me-photos">
      <legend className="label">{p.legend}</legend>
      {!p.photos ? (
        <p className="muted">Loading the photo library…</p>
      ) : (
        <div className="me-photo-grid">
          {p.allowNone && (
            <label className="me-photo">
              <input type="radio" name={p.legend} checked={p.value === null} onChange={() => p.onChange(null)} />
              <span className="ph">None</span>
            </label>
          )}
          {p.photos.map((url) => (
            <label key={url} className="me-photo">
              <input type="radio" name={p.legend} checked={p.value === url} onChange={() => p.onChange(url)} />
              {/* eslint-disable-next-line @next/next/no-img-element -- library thumbnails */}
              <img src={url} width={72} height={54} loading="lazy" alt={photoName(url)} />
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

// ── restaurant details ─────────────────────────────────────────────────────────────────────

type Hours = Record<string, string[][]>;

function Details(p: {
  menu: MenuOut;
  busy: boolean;
  save: (what: string, call: () => Promise<MenuOut>) => Promise<boolean>;
  needPhotos: () => void;
  photos: string[] | null;
}) {
  const details = p.menu.details!;
  const [hours, setHours] = useState<Hours>(() => structuredClone(details.hours));
  const [prep, setPrep] = useState(String(details.prep_min));
  const [cover, setCover] = useState<string | null>(details.cover?.url ?? null);

  const setRange = (day: string, i: number, j: 0 | 1, value: string) =>
    setHours((h) => ({ ...h, [day]: (h[day] ?? []).map((r, k) => (k === i ? (j === 0 ? [value, r[1]] : [r[0], value]) : r)) }));

  return (
    <details className="tile me-details" onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && p.needPhotos()}>
      <summary>
        <span>Restaurant details</span>
        <small>{details.is_open ? "Taking orders" : "Closed by you"} · prep {details.prep_min} min</small>
      </summary>
      <div className="me-details-body">
        <div className="between me-open">
          <span id="open-label" className="label">
            Taking orders
          </span>
          <button
            type="button"
            role="switch"
            className="switch"
            aria-checked={details.is_open}
            aria-labelledby="open-label"
            aria-describedby="open-help"
            disabled={p.busy}
            onClick={() => void p.save("change opening", () => api<MenuOut>("/restaurant", { method: "PATCH", body: { is_open: !details.is_open } }))}
          />
        </div>
        <p id="open-help" className="muted">
          Off closes the kitchen now, whatever the hours say: it leaves &quot;open now&quot; and orders are refused.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            // An end of 00:00 on a 00:00 start means the whole day.
            const clean: Hours = Object.fromEntries(
              Object.entries(hours).map(([d, rs]) => [d, rs.map(([a, b]) => (a === "00:00" && b === "00:00" ? ["00:00", "24:00"] : [a, b]))]),
            );
            void p.save("save the details", () =>
              api<MenuOut>("/restaurant", { method: "PATCH", body: { hours: clean, prep_min: Number(prep), ...(cover ? { cover_url: cover } : {}) } }),
            ).then((ok) => ok && toast("Details saved", undefined, "ok"));
          }}
        >
          <label className="field me-prep">
            <span className="label">Prep time (minutes)</span>
            <input className="input num" type="number" min={5} max={90} required value={prep} onChange={(e) => setPrep(e.target.value)} />
          </label>

          <fieldset className="field me-hours">
            <legend className="label">Hours</legend>
            {DAYS.map(([key, label]) => {
              const ranges = hours[key] ?? [];
              return (
                <div key={key} className="me-day" role="group" aria-label={label}>
                  <div className="me-day-head">
                    <b>{label}</b>
                    {ranges.length === 0 && <span className="muted">Closed</span>}
                    {ranges.length < 3 && (
                      <button
                        type="button"
                        className="btn small ghost"
                        onClick={() => setHours((h) => ({ ...h, [key]: [...ranges, ["11:00", "23:00"]] }))}
                        aria-label={`Add hours on ${label}`}
                      >
                        Add hours
                      </button>
                    )}
                  </div>
                  {ranges.map((r, i) => (
                    <span key={i} className="me-range">
                      <input
                        className="input"
                        type="time"
                        aria-label={`${label} opens`}
                        value={r[0]}
                        required
                        onChange={(e) => setRange(key, i, 0, e.target.value)}
                      />
                      <span aria-hidden="true">to</span>
                      <input
                        className="input"
                        type="time"
                        aria-label={`${label} closes`}
                        value={r[1] === "24:00" ? "00:00" : r[1]}
                        required
                        onChange={(e) => setRange(key, i, 1, e.target.value)}
                      />
                      {r[0] === "00:00" && (r[1] === "24:00" || r[1] === "00:00") && <small className="muted">all day</small>}
                      <button
                        type="button"
                        className="btn small ghost"
                        aria-label={`Remove ${label} hours ${r[0]} to ${r[1]}`}
                        onClick={() => setHours((h) => ({ ...h, [key]: ranges.filter((_, k) => k !== i) }))}
                      >
                        Remove
                      </button>
                    </span>
                  ))}
                </div>
              );
            })}
            <small className="muted">A closing time before the opening time runs past midnight.</small>
          </fieldset>

          <PhotoPicker legend="Cover photo" photos={p.photos} value={cover} onChange={setCover} />

          <button className="btn" disabled={p.busy}>
            {p.busy ? "Saving…" : "Save details"}
          </button>
        </form>
      </div>
    </details>
  );
}
