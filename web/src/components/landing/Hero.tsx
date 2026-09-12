export function Hero() {
  return (
    <section className="wrap hero">
      <div>
        <h1>Watch your dinner <span>ride over</span></h1>
        <p className="lede">Order from restaurants near you in Bengaluru, and follow the rider on the map from the kitchen door to yours — with an arrival time that actually updates.</p>
        <div className="search"><span className="pin" aria-hidden="true"></span><span>Deliver to: 4th Block, Koramangala</span><a className="btn btn-tomato" href="#near">Find food</a></div>
        <p className="small">Pay by UPI, card, or cash at the door.</p>
      </div>

      <div className="map" aria-label="Live delivery tracking example">
        <svg viewBox="0 0 600 520" aria-hidden="true">
          <g stroke="#E6D8C2" strokeWidth="10" strokeLinecap="round">
            <path d="M0 120 H600"/><path d="M0 260 H600"/><path d="M0 400 H600"/>
            <path d="M110 0 V520"/><path d="M300 0 V520"/><path d="M470 0 V520"/>
          </g>
          <g stroke="#EFE4D1" strokeWidth="5"><path d="M0 60 H600"/><path d="M0 190 H600"/><path d="M0 330 H600"/><path d="M0 460 H600"/><path d="M200 0 V520"/><path d="M390 0 V520"/><path d="M540 0 V520"/></g>
          <rect x="130" y="140" width="50" height="34" rx="4" fill="#DCEBD9"/><rect x="320" y="280" width="60" height="40" rx="4" fill="#DCEBD9"/><rect x="490" y="60" width="40" height="44" rx="4" fill="#F1D9C7"/>
          <path id="route" d="M110 400 H200 V260 H300 V190 H390 V120 H470" fill="none" stroke="#2F7D4A" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="2 12"/>
          <g transform="translate(110 400)"><circle r="16" fill="#E4402E" stroke="#FFF6E9" strokeWidth="4"/><text x="0" y="5" textAnchor="middle" fontSize="14" fontWeight="700" fill="#fff" fontFamily="inherit">R</text></g>
          <g transform="translate(470 120)"><circle r="16" fill="#2B2B2B" stroke="#FFF6E9" strokeWidth="4"/><text x="0" y="5" textAnchor="middle" fontSize="14" fontWeight="700" fill="#fff" fontFamily="inherit">You</text></g>
          <g className="bike">
            <circle r="13" fill="#2F7D4A" stroke="#FFF6E9" strokeWidth="4"/>
            <animateMotion dur="9s" repeatCount="indefinite" rotate="0"><mpath href="#route"/></animateMotion>
          </g>
        </svg>
        <div className="rider"><i aria-hidden="true"></i>Suresh <em>· 4.9 · 1,240 deliveries</em></div>
        <div className="status">
          <div className="top"><span>Picked up from <b>Meghana Foods</b></span><span className="eta">11 min</span></div>
          <div className="steps" aria-hidden="true"><span className="on"></span><span className="on"></span><span className="now"></span><span></span></div>
          <div className="labels"><span>Placed 7:42</span><span>Accepted 7:43</span><span>On the way</span><span>Delivered</span></div>
        </div>
      </div>
    </section>
  );
}
