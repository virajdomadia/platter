"""ApiError → one envelope everywhere (06 §C): `{ "error": { "code", "message", "details" } }`."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(message: str = "Not found") -> ApiError:
    return ApiError(404, "not_found", message)


def envelope(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


async def _api_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    return envelope(exc.status, exc.code, exc.message, exc.details)


async def _validation(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    fields: dict[str, str] = {}
    for e in exc.errors():
        path = ".".join(str(p) for p in e["loc"][1:]) or "body"
        fields.setdefault(path, str(e["msg"]).removeprefix("Value error, "))
    return envelope(422, "validation", "Some fields need another look", {"fields": fields})


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    if exc.status_code in (404, 405):
        return envelope(404, "not_found", "Not found")
    code = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(
        exc.status_code, "error"
    )
    return envelope(exc.status_code, code, str(exc.detail))


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return envelope(500, "internal", "Something went wrong on our side")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
