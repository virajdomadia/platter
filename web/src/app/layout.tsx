import type { Metadata } from "next";
import { Bricolage_Grotesque } from "next/font/google";
const sans = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-sans", display: "swap", axes: ["opsz"] });
import "./globals.css";

export const metadata: Metadata = {
  title: "Platter \u2014 hot food, tracked to your door",
  description: "Order from restaurants near you in Bengaluru and follow the rider on the map to your door.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
