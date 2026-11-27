// Server-side reads (RSC): straight to the API host with the visitor's cookie forwarded.
import "server-only";
import { cookies } from "next/headers";
import type { Me } from "./api";

export const API_URL = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");

export async function serverFetch<T>(
  path: string,
  init: { auth?: boolean; tags?: string[]; revalidate?: number } = {},
): Promise<{ status: number; data: T | null }> {
  const headers: Record<string, string> = {};
  if (init.auth) {
    const jar = await cookies();
    const session = jar.get("pl_session");
    if (!session) return { status: 401, data: null };
    headers.cookie = `pl_session=${session.value}`;
  }
  try {
    const res = await fetch(`${API_URL}${path}`, {
      headers,
      ...(init.auth
        ? { cache: "no-store" as const }
        : { next: { tags: init.tags, revalidate: init.revalidate ?? 300 } }),
    });
    if (!res.ok) return { status: res.status, data: null };
    return { status: res.status, data: (await res.json()) as T };
  } catch {
    return { status: 503, data: null };
  }
}

export async function getMe(): Promise<Me | null> {
  const { data } = await serverFetch<Me>("/auth/me", { auth: true });
  return data;
}
