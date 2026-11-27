import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

const RESTAURANTS = [
  "bandstand-kitchen", "dosa-camp", "biryani-bhatti", "thali-ghar", "momo-junction", "forno-17",
  "burger-barn", "idli-hut", "sweet-tooth", "tapri-tales", "punjabi-rasoi", "pav-bhaji-corner",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date("2026-11-26");
  return [
    { url: `${SITE_URL}/`, lastModified: now, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/sign-in`, lastModified: now, changeFrequency: "monthly", priority: 0.3 },
    ...RESTAURANTS.map((slug) => ({ url: `${SITE_URL}/r/${slug}`, lastModified: now, changeFrequency: "weekly" as const, priority: 0.7 })),
  ];
}
