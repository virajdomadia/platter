export function Header() {
  return (
    <header className="wrap">
      <nav className="nav" aria-label="Main">
        <a className="logo" href="#"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="32" fill="#E4402E"/><circle cx="32" cy="32" r="20" fill="#FFF6E9"/><circle cx="32" cy="32" r="11" fill="#E4402E"/><path d="M44 12 c6 0 10 4 10 9 c0 7 -10 17 -10 17 s-10 -10 -10 -17 c0 -5 4 -9 10 -9 z" fill="#2F7D4A" stroke="#FFF6E9" strokeWidth="2.5"/><circle cx="44" cy="21" r="3.5" fill="#FFF6E9"/></svg>Platter</a>
        <ul><li><a href="#near">Restaurants</a></li><li><a href="#sides">For restaurants</a></li><li><a href="#sides">Ride with us</a></li></ul>
        <a className="btn btn-line" href="#">Sign in</a>
      </nav>
    </header>
  );
}
