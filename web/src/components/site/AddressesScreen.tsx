"use client";

// S11: saved addresses with pins; add one by search or by dragging the pin, delete, or deliver here.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Map } from "@/components/map/Map";
import { api, errorMessage, type Address, type Place } from "@/lib/api";
import { setPin, usePin } from "@/lib/pin";
import { useMe } from "@/lib/session";
import { toast } from "@/lib/toast";
import { AddressSearch } from "./AddressSearch";

const ICON: Record<string, string> = { home: "🏠", office: "💼", work: "💼" };

export function AddressesScreen() {
  const me = useMe();
  const router = useRouter();
  const pin = usePin();
  const [list, setList] = useState<Address[] | null>(null);
  const [draft, setDraft] = useState({ lat: pin.lat, lng: pin.lng, label: "", line: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (me === null) router.replace("/sign-in?next=/addresses");
    if (me) api<Address[]>("/addresses").then(setList).catch(() => setList([]));
  }, [me, router]);

  const save = async () => {
    setSaving(true);
    try {
      const a = await api<Address>("/addresses", { body: draft });
      setList((l) => [...(l ?? []), a]);
      setDraft((d) => ({ ...d, label: "", line: "" }));
      toast("Address saved", `${a.label} · ${a.line}`, "ok");
    } catch (err) {
      toast("Couldn't save", errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (a: Address) => {
    try {
      await api(`/addresses/${a.id}`, { method: "DELETE" });
      setList((l) => (l ?? []).filter((x) => x.id !== a.id));
    } catch (err) {
      toast("Couldn't delete", errorMessage(err));
    }
  };

  return (
    <main id="main" className="page narrow">
      <h1 style={{ fontSize: 24, margin: "6px 4px 12px" }}>Addresses</h1>
      <div className="grid2">
        <div className="tile flush span2" style={{ height: 240, position: "relative" }}>
          <Map
            label="New address pin, drag to place"
            center={[draft.lat, draft.lng]}
            zoom={15}
            draggable={{ lat: draft.lat, lng: draft.lng, onDragEnd: (lat, lng) => setDraft((d) => ({ ...d, lat, lng })) }}
          >
            <span className="map-pill">Drag the pin to the door</span>
          </Map>
        </div>
        <div className="span2">
          <AddressSearch
            near={draft}
            onPick={(p: Place) => setDraft((d) => ({ ...d, lat: p.lat, lng: p.lng, line: d.line || [p.label, p.line].join(", ") }))}
          />
        </div>
        <form
          className="tile span2 stack"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="grid2">
            <label className="field">
              <span className="label">Label</span>
              <input className="input" required maxLength={40} placeholder="Home, Office…" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
            </label>
            <label className="field">
              <span className="label">Flat, street, landmark</span>
              <input className="input" required minLength={3} maxLength={200} placeholder="Flat, street" value={draft.line} onChange={(e) => setDraft({ ...draft, line: e.target.value })} />
            </label>
          </div>
          <button className="btn" disabled={saving || !me}>
            {saving ? "Saving…" : "＋ Save this pin"}
          </button>
        </form>
        {list === null && [0, 1].map((i) => <div key={i} className="skeleton" style={{ height: 120 }} />)}
        {list?.length === 0 && <p className="muted span2" style={{ padding: 8 }}>No saved addresses yet. Drop the pin and save one.</p>}
        {list?.map((a) => (
          <div key={a.id} className={`tile spring ${pin.addressId === a.id ? "lav" : ""}`} style={{ display: "grid", gap: 6, alignContent: "start" }}>
            <span style={{ fontSize: 22 }} aria-hidden="true">
              {ICON[a.label.toLowerCase()] ?? "📍"}
            </span>
            <b>{a.label}</b>
            <small style={{ fontWeight: 700, fontSize: 12, color: "var(--ink2)" }}>{a.line}</small>
            <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
              <button
                className="chip dark"
                onClick={() => {
                  setPin({ lat: a.lat, lng: a.lng, label: a.label, line: a.line, addressId: a.id });
                  router.push("/");
                }}
              >
                Deliver here
              </button>
              <button className="chip" onClick={() => remove(a)} aria-label={`Delete ${a.label}`}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
