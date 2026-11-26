"use client";

// MapLibre is ~800 kB; it loads only on pages that show a map, after first paint.
import dynamic from "next/dynamic";

export type { MapMarker, MapRoute } from "./LiveMap";

export const Map = dynamic(() => import("./LiveMap"), {
  ssr: false,
  loading: () => <div className="skeleton" style={{ position: "absolute", inset: 0 }} aria-hidden="true" />,
});
