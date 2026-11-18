import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // The landing page ships only SVGs from public/, so the optimizer has nothing to do. Off, so no
  // request can ever spend Vercel Hobby's 5,000 monthly image transformations.
  images: { unoptimized: true },
};

export default nextConfig;
