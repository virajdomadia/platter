import type { Metadata } from "next";
import { AddressesScreen } from "@/components/site/AddressesScreen";

export const metadata: Metadata = { title: "Addresses", robots: { index: false } };

export default function AddressesPage() {
  return <AddressesScreen />;
}
