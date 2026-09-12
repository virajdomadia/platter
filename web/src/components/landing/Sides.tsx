export function Sides() {
  return (
    <section className="sides" id="sides">
      <div className="wrap">
        <h2>One order, three screens, no phone calls</h2>
        <p className="sub">The customer, the kitchen and the rider each see exactly what they need — and every tap moves the same order forward.</p>
        <div className="sgrid">
          <div className="s"><h3>Customer</h3><p>Pin your address, order, pay, and follow the rider on the map until the doorbell rings.</p>
            <div className="ui"><div className="o"><b>#4821 · Meghana Foods</b><span className="k g">On the way</span></div><div className="o"><b>#4816 · Truffles</b><span className="k g">Delivered</span></div></div></div>
          <div className="s"><h3>Restaurant</h3><p>A tablet board of incoming orders. Accept, mark ready, switch off a dish that's run out.</p>
            <div className="ui"><div className="o"><b>#4823 · 2 items</b><span className="k">New</span></div><div className="o"><b>#4821 · 3 items</b><span className="k g">Ready</span></div><div className="tog"><span>Chicken biryani</span><i aria-hidden="true"></i></div></div></div>
          <div className="s"><h3>Rider</h3><p>Next pickup, the drop on a map, and one switch to share your location while you ride.</p>
            <div className="ui"><div className="tog"><span>Sharing location</span><i aria-hidden="true"></i></div><div className="o"><b>Pickup · Meghana Foods</b><span className="k g">Done</span></div><div className="o"><b>Drop · 4th Block</b><span className="k">1.1 km</span></div></div></div>
        </div>
      </div>
    </section>
  );
}
