import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";

export const alt = "Platter — watch your dinner ride over";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  // Bricolage Grotesque, the site's typeface, committed under src/assets (SIL OFL 1.1) so the build never fetches fonts.
  const dir = join(process.cwd(), "src/assets");
  const [bold, medium] = await Promise.all([
    readFile(join(dir, "BricolageGrotesque-ExtraBold.ttf")),
    readFile(join(dir, "BricolageGrotesque-Medium.ttf")),
  ]);
  const fonts = [
    { name: "Bricolage", data: bold, weight: 800 as const, style: "normal" as const },
    { name: "Bricolage", data: medium, weight: 500 as const, style: "normal" as const },
  ];

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: "#F3F0FF", color: "#1F1B2E", fontFamily: "Bricolage", padding: "60px 64px" }}>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", width: 560 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 38, fontWeight: 800, letterSpacing: "-0.03em" }}>
            <svg width="56" height="56" viewBox="0 0 64 64"><circle cx="32" cy="32" r="32" fill="#FF7A59"/><circle cx="32" cy="32" r="20" fill="#F3F0FF"/><circle cx="32" cy="32" r="11" fill="#FF7A59"/><path d="M44 12 c6 0 10 4 10 9 c0 7 -10 17 -10 17 s-10 -10 -10 -17 c0 -5 4 -9 10 -9 z" fill="#7B5CFF" stroke="#F3F0FF" strokeWidth="2.5"/><circle cx="44" cy="21" r="3.5" fill="#F3F0FF"/></svg>
            Platter
          </div>
          <div style={{ display: "flex", flexDirection: "column", fontSize: 92, fontWeight: 800, lineHeight: 0.98, letterSpacing: "-0.04em" }}>
            <span>Watch your</span>
            <span>dinner</span>
            <span style={{ color: "#7B5CFF" }}>ride over</span>
          </div>
          <div style={{ display: "flex", fontSize: 26, fontWeight: 500, color: "#3B3552" }}>
            Food delivery in Bengaluru, tracked live to your door
          </div>
        </div>
        <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "flex-end" }}>
          <div style={{ display: "flex", position: "relative", width: 470, height: 500, borderRadius: 32, border: "3px solid #1F1B2E", background: "#E6DEFF", overflow: "hidden" }}>
            <svg width="470" height="500" viewBox="0 0 600 640">
              <g stroke="#D8D0F5" strokeWidth="12" strokeLinecap="round"><path d="M0 120 H600"/><path d="M0 300 H600"/><path d="M0 480 H600"/><path d="M110 0 V640"/><path d="M300 0 V640"/><path d="M470 0 V640"/></g>
              <g stroke="#E6DEFF" strokeWidth="6"><path d="M0 210 H600"/><path d="M0 390 H600"/><path d="M200 0 V640"/><path d="M390 0 V640"/></g>
              <path d="M110 300 H200 V210 H300 V120 H470" fill="none" stroke="#7B5CFF" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="2 14"/>
              <circle cx="110" cy="300" r="22" fill="#FF7A59" stroke="#F3F0FF" strokeWidth="5"/>
              <circle cx="470" cy="120" r="22" fill="#1F1B2E" stroke="#F3F0FF" strokeWidth="5"/>
              <circle cx="250" cy="210" r="17" fill="#7B5CFF" stroke="#F3F0FF" strokeWidth="5"/>
            </svg>
            <div style={{ display: "flex", position: "absolute", left: 20, right: 20, bottom: 20, justifyContent: "space-between", alignItems: "center", background: "#fff", border: "3px solid #1F1B2E", borderRadius: 22, padding: "18px 22px" }}>
              <div style={{ display: "flex", flexDirection: "column", fontSize: 22, fontWeight: 800 }}>
                <span>On the way</span>
                <span style={{ fontSize: 18, fontWeight: 500, color: "#3B3552" }}>Suresh · 4.9</span>
              </div>
              <span style={{ fontSize: 40, fontWeight: 800, letterSpacing: "-0.03em" }}>11 min</span>
            </div>
          </div>
        </div>
      </div>
    ),
    { ...size, fonts },
  );
}
