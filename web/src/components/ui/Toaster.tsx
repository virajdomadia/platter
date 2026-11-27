"use client";

import { useToast } from "@/lib/toast";

export function Toaster() {
  const t = useToast();
  return (
    <div aria-live="polite" role="status">
      {t && (
        <div key={t.id} className={`toast ${t.tone === "ok" ? "ok" : ""}`}>
          <b>{t.title}</b>
          {t.body}
        </div>
      )}
    </div>
  );
}
