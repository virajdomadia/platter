import type { NextConfig } from "next";

// The browser only ever talks to this origin: `/api/*` is rewritten to the FastAPI app, so the
// session cookie is first-party and EventSource is same-origin. Map tiles come from OpenFreeMap
// (no key); Razorpay's Checkout script and frame are allowed for online payment (test mode).
const API_URL = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");
const isDev = process.env.NODE_ENV !== "production";
const TILES = "https://tiles.openfreemap.org";
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' https://checkout.razorpay.com${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob: ${TILES} https://*.razorpay.com`,
  "font-src 'self'",
  `connect-src 'self' ${TILES} https://api.razorpay.com https://lumberjack.razorpay.com`,
  "worker-src 'self' blob:",
  "child-src blob:",
  "frame-src https://api.razorpay.com https://checkout.razorpay.com",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "object-src 'none'",
  "form-action 'self'",
  "manifest-src 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Permissions-Policy",
    value:
      'camera=(), microphone=(), geolocation=(self), payment=(self "https://api.razorpay.com"), usb=(), browsing-topics=()',
  },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Dish photos are pre-sized 480-px thumbnails committed under public/dishes; the optimizer stays
  // off so no request can spend Vercel Hobby's monthly image transformations.
  images: { unoptimized: true },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache" }] },
    ];
  },
  async rewrites() {
    // Filesystem routes win (app/api/revalidate), everything else under /api goes to FastAPI.
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default nextConfig;
