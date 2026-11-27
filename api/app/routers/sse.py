"""One way to answer with a stream (04 §3 headers)."""

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory
from app.services import auth, limits
from app.services import stream as stream_service

# shortcut: caps how often one browser session opens a scope's stream (a reconnect is every 280 s),
# not how many it holds open at once; a held-lease row per (session, scope) if abuse shows up.
OPENS_PER_MIN = 6

HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


async def respond(
    request: Request,
    db: AsyncSession,
    scope: stream_service.Scope,
    since: str | None,
    on_tick: Callable | None = None,
) -> StreamingResponse:
    session = auth.hash_token(request.cookies.get(auth.COOKIE, ""))[:16]
    await limits.hit(db, f"stream:{scope.kind}:{session}", OPENS_PER_MIN)
    await db.close()  # the stream opens its own short session per tick
    cursor = stream_service.parse_cursor(request.headers.get("last-event-id") or since)
    is_disconnected: Callable[[], Awaitable[bool]] = request.is_disconnected
    body = stream_service.stream(
        session_factory(request.app),
        scope,
        cursor,
        is_disconnected=is_disconnected,
        lifetime_s=request.app.state.settings.stream_lifetime_s,
        on_tick=on_tick,
    )
    return StreamingResponse(body, media_type="text/event-stream", headers=HEADERS)
