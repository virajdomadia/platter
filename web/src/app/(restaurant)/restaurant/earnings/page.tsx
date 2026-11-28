import type { Metadata } from "next";
import { BoardTabs } from "@/components/board/BoardTabs";
import { EarningsView } from "@/components/money/Earnings";
import { RoleBar } from "@/components/ui/RoleBar";
import "@/components/board/board.css";

export const metadata: Metadata = { title: "Earnings", robots: { index: false } };

export default function RestaurantEarningsPage() {
  return (
    <>
      <RoleBar title="Earnings" subtitle="80% of the food on every delivered order" who="🍳 Kitchen">
        <BoardTabs current="earnings" />
      </RoleBar>
      <EarningsView path="/restaurant/earnings" />
    </>
  );
}
