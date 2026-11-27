// The API calls this when a kitchen switches a dish on or off, so the cached restaurant page
// refreshes at once instead of after its 5-minute window.
import { revalidateTag } from "next/cache";
import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const secret = process.env.REVALIDATE_SECRET;
  const body = (await req.json().catch(() => null)) as { tags?: unknown; secret?: unknown } | null;
  if (!secret || !body || body.secret !== secret) return NextResponse.json({ ok: false }, { status: 401 });
  const tags = Array.isArray(body.tags) ? body.tags.filter((t): t is string => typeof t === "string").slice(0, 20) : [];
  tags.forEach((t) => revalidateTag(t));
  return NextResponse.json({ ok: true, tags });
}
