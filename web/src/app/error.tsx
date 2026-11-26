"use client";

import Link from "next/link";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main id="main" className="page narrow" style={{ paddingTop: 40 }}>
      <div className="tile peach spring" style={{ display: "grid", gap: 10, justifyItems: "start" }}>
        <h1 style={{ fontSize: 24 }}>Something went wrong on our side</h1>
        <p>We couldn&apos;t reach the kitchen just now. Try again in a moment.</p>
        <div className="row">
          <button className="btn" onClick={reset}>Try again</button>
          <Link className="btn ghost" href="/">Home</Link>
        </div>
      </div>
    </main>
  );
}
