"""One way to answer with a stream (04 §3 headers)."""

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.core.db import session_factory
from app.services import stream as stream_service

HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def respond(
    request: Request,
    scope: stream_service.Scope,
    since: str | None,
    on_tick: Callable | None = None,
) -> StreamingResponse:
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
