import { BottomNav, TopBar } from "@/components/site/SiteNav";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <TopBar />
      {children}
      <BottomNav />
    </>
  );
}
