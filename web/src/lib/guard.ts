// Role-gated layouts (R1): the board, the rider app and the admin answer 404 to anyone else — the
// same as the API — so they don't admit they exist.
import "server-only";
import { notFound, redirect } from "next/navigation";
import type { Me, Role } from "./api";
import { getMe } from "./server";

export async function requireRole(role: Role, path: string): Promise<Me> {
  const me = await getMe();
  if (!me) redirect(`/sign-in?next=${encodeURIComponent(path)}`);
  if (me.role !== role) notFound();
  return me;
}
