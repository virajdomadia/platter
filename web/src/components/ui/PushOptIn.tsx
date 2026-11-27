"use client";

// Asks once, at the moment it matters (after an order, on the board, going online). Hidden when
// push is unsupported, switched off, or already on; a blocked permission says where to fix it.
import { usePush } from "@/lib/push";

export function PushOptIn({
  children,
  className = "",
  compact = false,
}: {
  children: React.ReactNode;
  className?: string;
  compact?: boolean; // a header button; `children` becomes its description
}) {
  const { state, enable, busy } = usePush();
  if (state === "loading" || state === "unsupported" || state === "on") return null;
  if (compact) {
    if (state !== "off") return null;
    return (
      <button type="button" className="btn small ghost" onClick={() => void enable()} disabled={busy} title={String(children)}>
        {busy ? "Turning on…" : "Notify me"}
        <span className="sr-only">: {children}</span>
      </button>
    );
  }
  return (
    <div className={`tile push-optin ${className}`} role="note">
      <span>
        {state === "denied"
          ? "Notifications are blocked for this site. Allow them in the browser's site settings to get alerts with the tab closed."
          : children}
      </span>
      {state === "off" && (
        <button type="button" className="btn small" onClick={() => void enable()} disabled={busy}>
          {busy ? "Turning on…" : "Turn on notifications"}
        </button>
      )}
    </div>
  );
}
