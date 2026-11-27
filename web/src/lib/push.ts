// Web Push opt-in (v2 L2). One hook for the three places that ask: the tracking page after an
// order, the kitchen board, the rider going online. The browser keeps the subscription; the API
// ties it to this sign-in, so each visit re-sends it (signing out or a new account moves it).
"use client";

import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "./api";
import { toast } from "./toast";

export type PushState = "loading" | "unsupported" | "off" | "on" | "denied";

function supported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function keyBytes(b64: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function send(sub: PushSubscription): Promise<void> {
  const json = sub.toJSON();
  await api("/push/subscribe", { body: { endpoint: json.endpoint, keys: json.keys } });
}

export function usePush(): { state: PushState; enable: () => Promise<void>; busy: boolean } {
  const [state, setState] = useState<PushState>("loading");
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      if (!supported()) return setState("unsupported");
      const { key } = await api<{ key: string | null }>("/push/key").catch(() => ({ key: null }));
      if (!live) return;
      if (!key) return setState("unsupported"); // push switched off on this deployment
      setKey(key);
      if (Notification.permission === "denied") return setState("denied");
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = await reg?.pushManager.getSubscription();
      if (sub && Notification.permission === "granted") {
        await send(sub).catch(() => undefined); // re-tie it to this sign-in
        if (live) setState("on");
      } else if (live) setState("off");
    })().catch(() => live && setState("unsupported"));
    return () => {
      live = false;
    };
  }, []);

  const enable = useCallback(async () => {
    if (!key) return;
    setBusy(true);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "denied" : "off");
        return;
      }
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      const sub =
        (await reg.pushManager.getSubscription()) ??
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) }));
      await send(sub);
      setState("on");
      toast("Notifications on", "You'll hear from Platter with this tab closed.", "ok");
    } catch (err) {
      toast("Couldn't turn on notifications", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, [key]);

  return { state, enable, busy };
}
