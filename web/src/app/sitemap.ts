import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

const RESTAURANTS = [
  "koramangala-social", "dosa-camp", "biryani-bhatti", "thali-ghar", "momo-junction", "pizza-bakery",
  "burger-barn", "idli-hut", "sweet-tooth", "chai-point", "punjabi-rasoi", "pav-bhaji-corner",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date("2026-11-26");
  return [
    { url: `${SITE_URL}/`, lastModified: now, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/sign-in`, lastModified: now, changeFrequency: "monthly", priority: 0.3 },
    ...RESTAURANTS.map((slug) => ({ url: `${SITE_URL}/r/${slug}`, lastModified: now, changeFrequency: "weekly" as const, priority: 0.7 })),
  ];
}
