"use client";

// Paints the whole page ink while the rider app is mounted (overscroll, safe areas).
import { useEffect } from "react";

export function BodyDark() {
  useEffect(() => {
    document.body.classList.add("dark");
    return () => document.body.classList.remove("dark");
  }, []);
  return null;
}
