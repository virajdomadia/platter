import { AUTHOR_URL } from "@/lib/site";

export function Footer() {
  return (
    <footer className="wrap foot">
      <span>Platter · a portfolio project by <a href={AUTHOR_URL}>Viraj Domadia</a></span>
      <span>platter.virajdomadia.com</span>
    </footer>
  );
}
