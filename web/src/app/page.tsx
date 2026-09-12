import { Header } from "@/components/landing/Header";
import { Hero } from "@/components/landing/Hero";
import { Near } from "@/components/landing/Near";
import { Sides } from "@/components/landing/Sides";
import { Flow } from "@/components/landing/Flow";
import { Cta } from "@/components/landing/Cta";
import { Footer } from "@/components/landing/Footer";

export default function Home() {
  return (
    <>
      <Header />
      <main>
        <Hero />
        <Near />
        <Sides />
        <Flow />
        <Cta />
      </main>
      <Footer />
    </>
  );
}
