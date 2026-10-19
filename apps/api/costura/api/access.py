"""Request id and access log around every HTTP call, including rate-limit refusals."""

import logging
import re
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from costura.audit import Actor, actor_var
from costura.metrics import http_requests
from costura.telemetry import request_id_var, resolve_request_id

log = logging.getLogger("costura.access")
_EMAIL = re.compile(r"[^/@\s]+@[^/@\s]+")


def logged_path(request: Request) -> str:
    """The route template when routing matched, otherwise the path with e-mail addresses
    replaced. A raw path would record the address in `/people/{email}`."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return _EMAIL.sub("{email}", request.url.path)


def metric_route(request: Request) -> str:
    """The route template, or `unmatched`: a raw path would grow one series per URL."""
    template = getattr(request.scope.get("route"), "path", None)
    return template if isinstance(template, str) and template else "unmatched"


async def access_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = resolve_request_id(request.headers.get("x-request-id"))
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    actor_token = actor_var.set(Actor())
    started = time.perf_counter()
    try:
        try:
            response = await call_next(request)
        except Exception:
            http_requests.observe(
                request.method, metric_route(request), 500, time.perf_counter() - started
            )
            log.exception("http %s %s failed", request.method, logged_path(request))
            raise
        response.headers["X-Request-ID"] = request_id
        elapsed = time.perf_counter() - started
        http_requests.observe(request.method, metric_route(request), response.status_code, elapsed)
        log.info(
            "http %s %s %s %.3fs",
            request.method,
            logged_path(request),
            response.status_code,
            elapsed,
        )
        return response
    finally:
        actor_var.reset(actor_token)
        request_id_var.reset(token)
