import asyncio
import logging
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
from fastapi import FastAPI, Request, Response
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from costura.api.deps import get_session
from costura.api.ratelimit import DEMO_PREFIX
from costura.models import OrganizationMember
from costura.models.organization import DEMO_ORG_SLUG, Organization

log = logging.getLogger("costura.demo_cache")

CACHE_HEADER = "X-Costura-Cache"
WARM_PAGES = (
    "/overview",
    "/anomalies",
    "/budgets",
    "/explore",
    "/inventory",
    "/reconcile",
    "/review",
    "/runs",
)
WARM_POLL_SECONDS = 30
WARM_TIMEOUT_SECONDS = 120

SessionFactory = Callable[[], Generator[Session]]


@dataclass(frozen=True)
class Generation:
    organization_id: int
    refreshed_at: datetime | None
    members: str
    day: date


@dataclass(frozen=True)
class Entry:
    headers: tuple[tuple[str, str], ...]
    body: bytes


class DemoCache:
    def __init__(self, capacity_bytes: int) -> None:
        self.capacity_bytes = capacity_bytes
        self._entries: OrderedDict[tuple[Generation, str], Entry] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def get(self, generation: Generation, target: str) -> Entry | None:
        with self._lock:
            entry = self._entries.get((generation, target))
            if entry is not None:
                self._entries.move_to_end((generation, target))
            return entry

    def put(self, generation: Generation, target: str, entry: Entry) -> None:
        if len(entry.body) > self.capacity_bytes:
            return
        with self._lock:
            previous = self._entries.pop((generation, target), None)
            if previous is not None:
                self._size -= len(previous.body)
            self._entries[(generation, target)] = entry
            self._size += len(entry.body)
            while self._size > self.capacity_bytes:
                _, evicted = self._entries.popitem(last=False)
                self._size -= len(evicted.body)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._size = 0

    @property
    def size_bytes(self) -> int:
        return self._size

    def __len__(self) -> int:
        return len(self._entries)


def session_factory(app: FastAPI) -> SessionFactory:
    return app.dependency_overrides.get(get_session, get_session)


def current_generation(sessions: SessionFactory, today: date | None = None) -> Generation | None:
    members = (
        select(
            func.coalesce(
                func.string_agg(
                    func.concat(OrganizationMember.user_id, ":", OrganizationMember.role),
                    aggregate_order_by(literal(","), OrganizationMember.user_id),
                ),
                "",
            )
        )
        .where(OrganizationMember.organization_id == Organization.id)
        .scalar_subquery()
    )
    with contextmanager(sessions)() as session:
        row = session.execute(
            select(
                Organization.id,
                Organization.is_demo,
                Organization.demo_refreshed_at,
                members.label("members"),
            ).where(Organization.slug == DEMO_ORG_SLUG)
        ).one_or_none()
    if row is None or not row.is_demo:
        return None
    return Generation(row.id, row.demo_refreshed_at, row.members, today or datetime.now(UTC).date())


def cacheable(request: Request) -> bool:
    path = request.url.path
    return (
        request.method == "GET"
        and "authorization" not in request.headers
        and "origin" not in request.headers
        and (path == DEMO_PREFIX or path.startswith(DEMO_PREFIX + "/"))
    )


async def demo_cache_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    cache: DemoCache | None = getattr(request.app.state, "demo_cache", None)
    if cache is None or not cacheable(request):
        return await call_next(request)
    generation = await run_in_threadpool(current_generation, session_factory(request.app))
    if generation is None:
        return await call_next(request)
    query = request.url.query
    target = f"{request.url.path}?{query}" if query else request.url.path
    entry = cache.get(generation, target)
    if entry is not None:
        return Response(entry.body, headers={**dict(entry.headers), CACHE_HEADER: "hit"})
    response = await call_next(request)
    chunks = getattr(response, "body_iterator", None)
    if response.status_code != 200 or chunks is None:
        return response
    body = b"".join([chunk async for chunk in chunks])
    headers = tuple(
        (name, value) for name, value in response.headers.items() if name != "content-length"
    )
    cache.put(generation, target, Entry(headers, body))
    return Response(body, headers={**dict(headers), CACHE_HEADER: "miss"})


def _cookie_header(response: httpx.Response) -> str:
    return "; ".join(
        header.split(";", 1)[0].strip() for header in response.headers.get_list("set-cookie")
    )


async def warm(client: httpx.AsyncClient) -> int:
    opened = await client.get(f"/o/{DEMO_ORG_SLUG}")
    location = opened.headers.get("location", "")
    if not opened.is_redirect or location.endswith("/o/-missing"):
        raise RuntimeError(f"/o/{DEMO_ORG_SLUG} answered {opened.status_code} {location!r}")
    cookie = _cookie_header(opened)
    rendered = 0
    for page in WARM_PAGES:
        response = await client.get(page, headers={"cookie": cookie})
        if response.status_code == 200:
            rendered += 1
        else:
            log.warning("demo cache warm-up: %s answered %s", page, response.status_code)
    return rendered


async def warm_forever(
    app: FastAPI, base_url: str, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    warmed: Generation | None = None
    async with httpx.AsyncClient(
        base_url=base_url, timeout=WARM_TIMEOUT_SECONDS, transport=transport
    ) as client:
        while True:
            try:
                generation = await run_in_threadpool(current_generation, session_factory(app))
                if generation is not None and generation != warmed:
                    rendered = await warm(client)
                    warmed = generation
                    log.info("demo cache warmed: %d of %d pages", rendered, len(WARM_PAGES))
            except Exception as exc:
                log.warning("demo cache warm-up failed: %s", exc)
            await asyncio.sleep(WARM_POLL_SECONDS)
