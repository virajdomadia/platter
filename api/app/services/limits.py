"""Fixed-window rate limits kept in Postgres (`rate_limits`), so every API instance shares one count
(an in-process counter resets per serverless instance and limits nothing)."""

import datetime as dt
import hmac

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import Settings
from app.core.errors import ApiError

WINDOW_S = 60


def client_ip(request: Request, settings: Settings) -> str:
    """The visitor's address from headers a client can't forge: the web tier's forwarded address
    when it proves itself with PROXY_SECRET (browsers reach us through its `/api` rewrite, so
    otherwise every visitor shares the proxy's address), else the platform's `x-real-ip`, else the
    socket. Never the client-supplied `X-Forwarded-For`. (Frontrow's pattern.)"""
    secret = settings.proxy_secret
    forwarded = request.headers.get("x-platter-client-ip")
    proof = request.headers.get("x-platter-proxy", "")
    if secret and forwarded and hmac.compare_digest(proof, secret.get_secret_value()):
        return forwarded.strip()
    return request.headers.get("x-real-ip") or (
        request.client.host if request.client else "unknown"
    )


async def hit(db: AsyncSession, key: str, per_minute: int) -> None:
    """Count one request for `key`; 429 past `per_minute`. Commits, so a refused or failed request
    still counts — call it before any other write in the request."""
    now = clock.now().timestamp()
    window = dt.datetime.fromtimestamp(now - now % WINDOW_S, dt.UTC)
    hits = (
        await db.execute(
            text(
                "insert into rate_limits (key, window_start, hits) values (:k, :w, 1)"
                " on conflict (key) do update set hits = case when rate_limits.window_start"
                " = excluded.window_start then rate_limits.hits + 1 else 1 end,"
                " window_start = excluded.window_start returning hits"
            ),
            {"k": key[:200], "w": window},
        )
    ).scalar_one()
    await db.commit()
    if hits > per_minute:
        raise ApiError(429, "rate_limited", "Too many requests. Try again in a minute.")
