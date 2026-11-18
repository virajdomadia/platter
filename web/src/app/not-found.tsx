import type { Metadata } from "next";
import Link from "next/link";
import { LogoMark } from "@/components/landing/Logo";
import { Footer } from "@/components/landing/Footer";

export const metadata: Metadata = {
  title: "Page not found — Platter",
  robots: { index: false },
};

export default function NotFound() {
  return (
    <>
      <header className="wrap">
        <nav className="nav" aria-label="Main">
          <Link className="logo" href="/"><LogoMark />Platter</Link>
        </nav>
      </header>
      <main id="main" tabIndex={-1} className="wrap nf">
        <span className="tag">404</span>
        <h1>This address isn&apos;t on <span>our map</span></h1>
        <p>The page you&apos;re looking for doesn&apos;t exist. It may have moved, or the link may be mistyped.</p>
        <Link className="btn btn-tomato" href="/">Back to Platter</Link>
      </main>
      <Footer />
    </>
  );
}
