const places = [
  { name: "Godavari Mess", cuisine: "Andhra", km: "1.2 km", eta: "22 min", g: "linear-gradient(140deg,#E4402E,#8A2418)" },
  { name: "Tiffin Lane Café", cuisine: "South Indian", km: "0.8 km", eta: "17 min", g: "linear-gradient(140deg,#FFD166,#C98A1A)" },
  { name: "Stack & Bun", cuisine: "Burgers", km: "1.9 km", eta: "29 min", g: "linear-gradient(140deg,#2F7D4A,#1F5C36)" },
  { name: "Scoop Street", cuisine: "Desserts", km: "1.5 km", eta: "24 min", g: "linear-gradient(140deg,#F3E9D8,#C9A97E)" },
];

export function Near() {
  return (
    <section className="wrap near" id="near">
      <h2>Near 4th Block right now</h2>
      <p className="sub">Sorted by distance from your pin, with a delivery time that comes from real rider positions, not a guess.</p>
      <div className="rlist">
        {places.map((p) => (
          <article key={p.name} className="r" style={{ "--g": p.g } as React.CSSProperties}>
            <div className="img" aria-hidden="true"></div>
            <div className="b">
              <h3>{p.name}</h3>
              <div className="m"><span>{p.cuisine} · {p.km}</span><b>{p.eta}</b></div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
