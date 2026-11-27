// Typed fetch for the browser: everything goes to same-origin `/api/*` (rewritten to FastAPI), so the
// session cookie rides along and nothing needs CORS. Errors are the API's envelope only:
// `{ error: { code, message, details } }` → ApiError.
import type { components } from "./api-types";

type Schemas = components["schemas"];
export type Me = Schemas["Me"];
export type RestaurantCard = Schemas["RestaurantCard"];
export type RestaurantOut = Schemas["RestaurantOut"];
export type MenuItem = Schemas["MenuItemOut"];
export type Category = Schemas["CategoryOut"];
export type Place = Schemas["Place"];
export type Address = Schemas["AddressOut"];
export type Quote = Schemas["QuoteOut"];
export type OrderOut = Schemas["OrderOut"];
export type OrderStart = Schemas["OrderStart"];
export type OrderCard = Schemas["OrderCard"];
export type RouteOut = Schemas["RouteOut"];
export type EtaOut = Schemas["EtaOut"];
export type RiderFix = Schemas["RiderFix"];
export type StatusEvent = Schemas["StatusEventOut"];
export type Ticket = Schemas["Ticket"];
export type Board = Schemas["Board"];
export type MenuOut = Schemas["MenuOut"];
export type Job = Schemas["Job"];
export type RiderMe = Schemas["RiderMe"];
export type AdminMap = Schemas["AdminMap"];
export type AdminOrder = Schemas["AdminOrder"];
export type AdminRider = Schemas["AdminRider"];
export type PaymentsConfig = Schemas["PaymentsConfig"];
export type OrderStatus = OrderOut["status"];
export type Role = Me["role"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

type Init = { method?: string; body?: unknown; signal?: AbortSignal };

export async function api<T>(path: string, init: Init = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: init.method ?? (init.body === undefined ? "GET" : "POST"),
      headers: init.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: "same-origin",
      cache: "no-store",
      signal: init.signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "offline", "You seem to be offline. Check your connection and try again");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error;
    throw new ApiError(
      res.status,
      e?.code ?? "error",
      e?.message ?? "Something went wrong. Please try again",
      e?.details ?? {},
    );
  }
  return data as T;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Something went wrong. Please try again";
}
