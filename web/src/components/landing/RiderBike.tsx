"use client";

import { useEffect, useState } from "react";

/**
 * The rider dot on the hero map. SMIL <animateMotion> ignores CSS, so the animation element is only
 * rendered after mount when the user hasn't asked for reduced motion. Server render (and reduced
 * motion) shows the rider parked at a fixed point on the route.
 */
export function RiderBike() {
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: no-preference)");
    const update = () => setAnimate(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  return (
    <g className="bike" transform={animate ? undefined : "translate(250 190)"}>
      <circle r="13" fill="#2F7D4A" stroke="#FFF6E9" strokeWidth="4" />
      {animate && (
        <animateMotion dur="9s" repeatCount="indefinite" rotate="0">
          <mpath href="#route" />
        </animateMotion>
      )}
    </g>
  );
}
