import type { Metadata } from "next";
import { AvailabilityList } from "@/components/board/AvailabilityList";

export const metadata: Metadata = { title: "Menu availability", robots: { index: false } };

export default function RestaurantMenuPage() {
  return <AvailabilityList />;
}
