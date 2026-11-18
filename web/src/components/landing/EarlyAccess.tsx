import { REPO_URL } from "@/lib/site";

export function EarlyAccess() {
  return (
    <section className="wrap early" id="early-access" aria-labelledby="early-title">
      <div className="early-card">
        <span className="tag">In development</span>
        <h2 id="early-title">Platter isn&apos;t taking orders yet</h2>
        <p>
          Platter is being built as a portfolio project by Viraj Domadia. There are no accounts,
          restaurant partners or riders yet, so signing in, ordering and signing up to ride
          aren&apos;t available. The restaurants above are made up. The code is public: follow the
          build, or get in touch.
        </p>
        <div className="actions">
          <a className="btn btn-tomato" href={REPO_URL}>Follow the build on GitHub</a>
          <a className="btn btn-line" href="https://virajdomadia.com/#contact">Contact Viraj</a>
        </div>
      </div>
    </section>
  );
}
