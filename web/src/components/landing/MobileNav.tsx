"use client";

import { useEffect, useId, useRef, useState } from "react";

type NavLink = { href: string; label: string };

type Props = {
  links: NavLink[];
  /** Shown in the panel only on narrow phones, where the header button is hidden. */
  extra?: NavLink;
};

/** Menu button + panel shown below 900px, where the inline nav list is hidden. */
export function MobileNav({ links, extra }: Props) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onPointer = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!panelRef.current?.contains(t) && !buttonRef.current?.contains(t)) setOpen(false);
    };
    const wide = window.matchMedia("(min-width: 901px)");
    const onWide = () => wide.matches && setOpen(false);
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    wide.addEventListener("change", onWide);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
      wide.removeEventListener("change", onWide);
    };
  }, [open]);

  return (
    <div className="mnav">
      <button
        ref={buttonRef}
        type="button"
        className="menu-btn"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={open ? "burger x" : "burger"} aria-hidden="true"><i /><i /><i /></span>
        Menu
      </button>
      <div id={panelId} ref={panelRef} className="menu-panel" hidden={!open}>
        <ul>
          {links.map((l) => (
            <li key={l.href}>
              <a href={l.href} onClick={() => setOpen(false)}>{l.label}</a>
            </li>
          ))}
          {extra && (
            <li className="menu-extra">
              <a href={extra.href} onClick={() => setOpen(false)}>{extra.label}</a>
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
