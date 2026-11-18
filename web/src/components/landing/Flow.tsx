export function Flow() {
  return (
    <section className="wrap flow" id="how-it-works">
      <h2>Every order walks the same path, and only the right person can move it</h2>
      <p className="sub">A restaurant can't mark an order delivered; a rider can't accept one. The server checks who's tapping before anything changes — which is what keeps three apps honest.</p>
      <div className="chain" role="group" aria-label="Order states">
        <span data-who="customer">Placed</span><i aria-hidden="true"></i><span data-who="restaurant">Accepted</span><i aria-hidden="true"></i><span data-who="restaurant">Preparing</span><i aria-hidden="true"></i><span data-who="restaurant">Ready</span><i aria-hidden="true"></i><span data-who="rider">Picked up</span><i aria-hidden="true"></i><span data-who="rider">Delivered</span>
      </div>
      <div className="key"><span><b>Customer</b> places</span><span><b className="t">Restaurant</b> accepts, prepares, marks ready</span><span><b className="g">Rider</b> picks up, delivers</span></div>
    </section>
  );
}
