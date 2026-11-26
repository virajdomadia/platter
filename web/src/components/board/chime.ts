"use client";

// The new-order chime: a two-note WebAudio ding. Browsers only let audio start after a user gesture,
// so the "Sound on" chip is that gesture; the choice is remembered, and after a reload the first tap
// anywhere on the page re-unlocks the context.
import { useCallback, useEffect, useRef, useState } from "react";

const KEY = "platter.board.sound";

type AudioCtor = typeof AudioContext;

function audioCtor(): AudioCtor | undefined {
  const w = window as unknown as { AudioContext?: AudioCtor; webkitAudioContext?: AudioCtor };
  return w.AudioContext ?? w.webkitAudioContext;
}

export function useChime() {
  const ctxRef = useRef<AudioContext | null>(null);
  const [on, setOn] = useState(false);
  const onRef = useRef(on);
  onRef.current = on;

  useEffect(() => {
    try {
      setOn(localStorage.getItem(KEY) === "on");
    } catch {
      /* storage blocked: sound stays off */
    }
  }, []);

  const unlock = useCallback((): AudioContext | null => {
    if (!ctxRef.current) {
      const Ctor = audioCtor();
      if (!Ctor) return null;
      ctxRef.current = new Ctor();
    }
    if (ctxRef.current.state === "suspended") void ctxRef.current.resume().catch(() => undefined);
    return ctxRef.current;
  }, []);

  // Remembered "on" after a reload: unlock on the first gesture.
  useEffect(() => {
    if (!on) return;
    const once = () => unlock();
    window.addEventListener("pointerdown", once, { once: true });
    window.addEventListener("keydown", once, { once: true });
    return () => {
      window.removeEventListener("pointerdown", once);
      window.removeEventListener("keydown", once);
    };
  }, [on, unlock]);

  useEffect(() => () => void ctxRef.current?.close().catch(() => undefined), []);

  const ding = useCallback((ctx: AudioContext) => {
    const t0 = ctx.currentTime + 0.02;
    [
      { f: 880, at: 0 },
      { f: 1318.5, at: 0.16 },
    ].forEach(({ f, at }) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = f;
      gain.gain.setValueAtTime(0.0001, t0 + at);
      gain.gain.exponentialRampToValueAtTime(0.35, t0 + at + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + at + 0.7);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0 + at);
      osc.stop(t0 + at + 0.75);
    });
  }, []);

  /** Plays the chime if sound is on and the context has been unlocked. */
  const play = useCallback(() => {
    const ctx = ctxRef.current;
    if (!onRef.current || !ctx || ctx.state !== "running") return;
    ding(ctx);
  }, [ding]);

  const toggle = useCallback(() => {
    const next = !onRef.current;
    setOn(next);
    try {
      localStorage.setItem(KEY, next ? "on" : "off");
    } catch {
      /* not remembered, still works this session */
    }
    if (next) {
      const ctx = unlock();
      if (ctx) ding(ctx); // a preview, and proof it's unlocked
    }
  }, [unlock, ding]);

  return { on, toggle, play };
}
