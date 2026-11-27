import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { RestaurantScreen } from "@/components/site/RestaurantScreen";
import type { RestaurantOut } from "@/lib/api";
import { serverFetch } from "@/lib/server";
import "@/components/site/site.css";

// Cached per restaurant (tag `restaurant:{slug}`, 5 min); the API revalidates the tag the moment the
// kitchen switches a dish off, so a sold-out dish disappears on the next request.
async function load(slug: string) {
  const { status, data } = await serverFetch<RestaurantOut>(`/restaurants/${encodeURIComponent(slug)}`, {
    tags: [`restaurant:${slug}`, "restaurants"],
    revalidate: 300,
  });
  if (status === 404) notFound();
  return data;
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const r = await load((await params).slug);
  if (!r) return { title: "Restaurant" };
  return {
    title: `${r.name} — ${r.cuisines.join(", ")}`,
    description: `Order from ${r.name} in ${r.area}, Bengaluru, and follow your rider live on the map.`,
    alternates: { canonical: `/r/${r.slug}` },
  };
}

export default async function RestaurantPage({ params }: { params: Promise<{ slug: string }> }) {
  const r = await load((await params).slug);
  if (!r) {
    return (
      <main id="main" className="page narrow">
        <div className="tile peach">
          <h1>This kitchen is out of reach right now</h1>
          <p className="muted">We couldn&apos;t load the menu. Try again in a moment.</p>
        </div>
      </main>
    );
  }
  return <RestaurantScreen restaurant={r} />;
}
