// Money is integer paise everywhere; distances metres; times seconds.

export function inr(paise: number): string {
  const rupees = paise / 100;
  return `₹${rupees.toLocaleString("en-IN", { maximumFractionDigits: rupees % 1 ? 2 : 0 })}`;
}

export function km(metres: number): string {
  if (metres < 1000) return `${Math.round(metres / 10) * 10} m`;
  return `${(metres / 1000).toFixed(1)} km`;
}

export function minutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}

export function etaLabel(seconds: number, method?: string): string {
  return `${method === "line" ? "≈ " : ""}${minutes(seconds)} min`;
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "Asia/Kolkata",
  });
}

export function day(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const opts = { timeZone: "Asia/Kolkata" } as const;
  const same = (a: Date, b: Date) =>
    a.toLocaleDateString("en-IN", opts) === b.toLocaleDateString("en-IN", opts);
  if (same(d, now)) return "Today";
  const y = new Date(now.getTime() - 86_400_000);
  if (same(d, y)) return "Yesterday";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", ...opts });
}

export function age(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export const STATUS_LABEL: Record<string, string> = {
  pending_payment: "Awaiting payment",
  placed: "Placed",
  accepted: "Accepted",
  preparing: "Cooking",
  ready: "Ready",
  picked_up: "On the way",
  delivered: "Delivered",
  rejected: "Rejected",
  cancelled: "Cancelled",
  expired: "Expired",
};

export function firstName(name: string): string {
  return name.split(" ")[0] || name;
}
