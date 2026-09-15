"""RFC 7807 ``application/problem+json`` helpers + FastAPI exception handlers
(docs/07 §3)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ApiError(Exception):
    """Raised by routers/services; rendered as problem+json."""

    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str,
        *,
        errors: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.errors = errors
        self.headers = headers or {}


def not_found(what: str) -> ApiError:
    return ApiError(404, "Not Found", f"{what} not found")


def conflict(detail: str, *, retry_after: int | None = None) -> ApiError:
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return ApiError(409, "Conflict", detail, headers=headers)


def _problem(
    request: Request,
    status_code: int,
    title: str,
    detail: str,
    *,
    errors: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": str(request.url.path),
    }
    if errors:
        body["errors"] = errors
    return JSONResponse(
        status_code=status_code, media_type=PROBLEM_MEDIA_TYPE, content=body, headers=headers
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _problem(
            request,
            exc.status_code,
            exc.title,
            exc.detail,
            errors=exc.errors,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"] if p != "body")
            fields[loc or "_"] = err["msg"]
        return _problem(
            request, 422, "Unprocessable Entity", "request validation failed", errors=fields
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(request, exc.status_code, "HTTP Error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return _problem(request, 500, "Internal Server Error", str(exc))
