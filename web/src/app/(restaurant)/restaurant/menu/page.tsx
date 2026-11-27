import type { Metadata } from "next";
import { MenuEditor } from "@/components/board/MenuEditor";

export const metadata: Metadata = { title: "Menu", robots: { index: false } };

export default function RestaurantMenuPage() {
  return <MenuEditor />;
}
