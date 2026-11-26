import Link from "next/link";

/** Board / Menu switch shown in the restaurant RoleBar. */
export function BoardTabs({ current }: { current: "board" | "menu" }) {
  return (
    <nav className="bd-tabs" aria-label="Kitchen">
      <Link href="/restaurant" aria-current={current === "board" ? "page" : undefined}>
        Board
      </Link>
      <Link href="/restaurant/menu" aria-current={current === "menu" ? "page" : undefined}>
        Menu
      </Link>
    </nav>
  );
}
