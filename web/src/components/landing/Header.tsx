import { LogoMark } from "./Logo";
import { MobileNav } from "./MobileNav";

const links = [
  { href: "#near", label: "Order food" },
  { href: "#for-restaurants", label: "For restaurants" },
  { href: "#for-riders", label: "Ride with us" },
];

export function Header() {
  return (
    <header className="wrap">
      <nav className="nav" aria-label="Main">
        <a className="logo" href="/"><LogoMark />Platter</a>
        <ul>{links.map((l) => <li key={l.href}><a href={l.href}>{l.label}</a></li>)}</ul>
        <div className="nav-end">
          <a className="btn btn-line" href="#early-access">Sign in</a>
          <MobileNav links={links} extra={{ href: "#early-access", label: "Sign in" }} />
        </div>
      </nav>
    </header>
  );
}
