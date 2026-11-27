"use client";

// Photon search through the API (bbox Bengaluru, 10/min/IP). If geocoding is down the pin still
// works — we say so instead of failing.
import { useEffect, useId, useRef, useState } from "react";
import { api, ApiError, type Place } from "@/lib/api";

export function AddressSearch({
  near,
  onPick,
  placeholder = "Search a street, a landmark…",
}: {
  near?: { lat: number; lng: number };
  onPick: (p: Place) => void;
  placeholder?: string;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const listId = useId();
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (q.trim().length < 3) {
      setResults([]);
      setNote(null);
      return;
    }
    const ctrl = new AbortController();
    timer.current = window.setTimeout(async () => {
      try {
        const qs = new URLSearchParams({ q: q.trim() });
        if (near) {
          qs.set("lat", String(near.lat));
          qs.set("lng", String(near.lng));
        }
        const found = await api<Place[]>(`/geo/search?${qs}`, { signal: ctrl.signal });
        setResults(found);
        setNote(found.length ? null : "No matches in Bengaluru. Try a nearby landmark, or drag the pin.");
        setOpen(true);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setResults([]);
        setNote(err instanceof ApiError && err.status !== 0 ? err.message : "Search is unavailable. Drop the pin instead.");
        setOpen(true);
      }
    }, 450);
    return () => ctrl.abort();
  }, [q, near]);

  return (
    <div style={{ position: "relative" }}>
      <label className="sr-only" htmlFor={`${listId}-input`}>
        Search for an address
      </label>
      <input
        id={`${listId}-input`}
        className="input"
        type="search"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        autoComplete="off"
        placeholder={`🔍 ${placeholder}`}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
      />
      {open && (results.length > 0 || note) && (
        <ul
          id={listId}
          role="listbox"
          className="tile"
          style={{ position: "absolute", left: 0, right: 0, top: "calc(100% + 6px)", zIndex: 20, listStyle: "none", margin: 0, padding: 6, boxShadow: "var(--shadow-pop)" }}
        >
          {note && <li className="muted" style={{ padding: 10, fontSize: 13 }}>{note}</li>}
          {results.map((p, i) => (
            <li key={`${p.lat},${p.lng},${i}`} role="option" aria-selected={false}>
              <button
                type="button"
                className="btn ghost block"
                style={{ justifyContent: "flex-start", textAlign: "left", display: "grid", gap: 0, background: "transparent" }}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onPick(p);
                  setQ("");
                  setOpen(false);
                }}
              >
                <b>{p.label}</b>
                <small className="muted" style={{ fontWeight: 700 }}>{p.line}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
