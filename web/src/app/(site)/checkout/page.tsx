import type { Metadata } from "next";
import { CheckoutScreen } from "@/components/site/CheckoutScreen";
import "@/components/site/site.css";

export const metadata: Metadata = { title: "Checkout", robots: { index: false } };

export default function CheckoutPage() {
  return <CheckoutScreen />;
}
