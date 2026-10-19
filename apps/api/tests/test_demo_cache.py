import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from costura.api.demo_cache import (
    CACHE_HEADER,
    WARM_PAGES,
    DemoCache,
    Entry,
    Generation,
    current_generation,
    warm,
)
from costura.api.deps import get_session
from costura.config import Settings, get_settings
from costura.demo.lifecycle import demo_org
from costura.main import app, create_app
from costura.models.organization import DEMO_ORG_SLUG
from tests.conftest import seed_sample, sign_in

DEMO = f"/api/v1/orgs/{DEMO_ORG_SLUG}"
SUMMARY = f"{DEMO}/providers/anthropic/months/2026-08/summary"


def test_an_anonymous_sample_read_is_served_from_memory_the_second_time(
    db_session: Session,
) -> None:
    seed_sample(db_session)
    anonymous = TestClient(app)

    first = anonymous.get(SUMMARY)
    second = anonymous.get(SUMMARY)

    assert first.status_code == second.status_code == 200
    assert first.headers[CACHE_HEADER] == "miss"
    assert second.headers[CACHE_HEADER] == "hit"
    assert second.json() == first.json()
    assert second.headers["content-type"] == first.headers["content-type"]
    ranged = anonymous.get(SUMMARY, params={"start": "2026-08-01", "end": "2026-08-10"})
    assert ranged.headers[CACHE_HEADER] == "miss"


def test_sessions_browsers_failures_and_other_organizations_bypass_the_cache(
    db_session: Session, owner_auth: str
) -> None:
    seed_sample(db_session)
    stranger = TestClient(app, headers={"Authorization": sign_in(db_session, "new@example.com")})
    anonymous = TestClient(app)

    for _ in range(2):
        assert CACHE_HEADER not in stranger.get(SUMMARY).headers
        assert CACHE_HEADER not in anonymous.get(SUMMARY, headers={"Origin": "x"}).headers
        missing = anonymous.get(f"{DEMO}/providers/nope/months/2026-08/summary")
        assert missing.status_code == 404 and CACHE_HEADER not in missing.headers
        member = TestClient(app, headers={"Authorization": owner_auth}).get("/api/v1/orgs/default")
        assert member.status_code == 200 and CACHE_HEADER not in member.headers
        assert CACHE_HEADER not in anonymous.get(f"{DEMO}2/setup").headers
    assert anonymous.post(f"{DEMO}/setup/dismiss").status_code == 401
    assert len(app.state.demo_cache) == 0


def test_a_new_dataset_day_or_member_is_a_new_generation(db_session: Session) -> None:
    seed_sample(db_session)
    sessions = app.dependency_overrides.get(get_session, get_session)
    today = date(2026, 9, 15)
    before = current_generation(sessions, today)
    assert before is not None
    assert current_generation(sessions, today) == before
    assert current_generation(sessions, today + timedelta(days=1)) != before

    org = demo_org(db_session)
    assert org is not None
    org.demo_refreshed_at = datetime.now(UTC) + timedelta(minutes=1)
    db_session.commit()
    anonymous = TestClient(app)
    anonymous.get(SUMMARY)
    assert current_generation(sessions, today) != before
    assert anonymous.get(SUMMARY).headers[CACHE_HEADER] == "hit"
    org.demo_refreshed_at = datetime.now(UTC) + timedelta(minutes=2)
    db_session.commit()
    assert anonymous.get(SUMMARY).headers[CACHE_HEADER] == "miss"

    sign_in(db_session, "ops@costura.example", owner_of=DEMO_ORG_SLUG)
    assert anonymous.get(SUMMARY).headers[CACHE_HEADER] == "miss"
    assert anonymous.get(SUMMARY).headers[CACHE_HEADER] == "hit"


def test_a_tenant_named_demo_is_never_cached(db_session: Session, owner_auth: str) -> None:
    from costura.orgs import create_org

    create_org(db_session, DEMO_ORG_SLUG, "Not the sample")
    db_session.commit()
    sessions = app.dependency_overrides.get(get_session, get_session)

    assert current_generation(sessions) is None
    assert TestClient(app).get(f"{DEMO}/setup").status_code == 401
    assert len(app.state.demo_cache) == 0


def test_hits_still_count_against_the_sample_rate_limit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_sample(db_session)
    monkeypatch.setattr(get_settings(), "costura_rate_limit_demo", 2)
    anonymous = TestClient(app)

    assert anonymous.get(SUMMARY).status_code == 200
    assert anonymous.get(SUMMARY).headers[CACHE_HEADER] == "hit"
    assert anonymous.get(SUMMARY).status_code == 429


def test_the_cache_evicts_the_least_recently_read_entries_past_its_capacity() -> None:
    cache = DemoCache(capacity_bytes=10)
    generation = Generation(1, None, "", date(2026, 9, 15))
    cache.put(generation, "/a", Entry((), b"aaaa"))
    cache.put(generation, "/b", Entry((), b"bbbb"))
    assert cache.get(generation, "/a") is not None
    cache.put(generation, "/c", Entry((), b"cccc"))

    assert cache.get(generation, "/b") is None
    assert cache.get(generation, "/a") is not None
    assert cache.get(generation, "/c") is not None
    assert cache.size_bytes == 8
    cache.put(generation, "/big", Entry((), b"x" * 11))
    assert cache.get(generation, "/big") is None
    assert cache.get(Generation(2, None, "", date(2026, 9, 15)), "/a") is None


def test_a_zero_budget_turns_the_cache_off() -> None:
    off = create_app(get_settings().model_copy(update={"costura_demo_cache_mb": 0}))
    on = create_app(get_settings().model_copy(update={"costura_demo_cache_mb": 2}))

    assert off.state.demo_cache is None
    assert on.state.demo_cache.capacity_bytes == 2 * 1024 * 1024
    assert Settings.model_fields["costura_demo_warm_url"].default == ""


def _web(seen: list[httpx.Request], *, missing: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == f"/o/{DEMO_ORG_SLUG}":
            location = "/o/-missing" if missing else "/overview"
            return httpx.Response(
                302,
                headers=[
                    ("location", location),
                    ("set-cookie", "__Host-costura_view=v1; Path=/; Secure; HttpOnly"),
                    ("set-cookie", "other=2; Path=/"),
                ],
            )
        return httpx.Response(200 if request.url.path != "/runs" else 500)

    return httpx.MockTransport(handler)


def test_the_warm_up_renders_every_sample_page_with_the_view_cookie() -> None:
    seen: list[httpx.Request] = []

    async def run() -> int:
        async with httpx.AsyncClient(base_url="http://web:3000", transport=_web(seen)) as client:
            return await warm(client)

    assert asyncio.run(run()) == len(WARM_PAGES) - 1
    assert [request.url.path for request in seen] == [f"/o/{DEMO_ORG_SLUG}", *WARM_PAGES]
    assert {request.headers["cookie"] for request in seen[1:]} == {
        "__Host-costura_view=v1; other=2"
    }


def test_the_warm_up_fails_without_a_published_sample() -> None:
    seen: list[httpx.Request] = []

    async def run() -> int:
        transport = _web(seen, missing=True)
        async with httpx.AsyncClient(base_url="http://web:3000", transport=transport) as client:
            return await warm(client)

    with pytest.raises(RuntimeError, match="-missing"):
        asyncio.run(run())
    assert len(seen) == 1


def test_the_warm_loop_renders_once_per_generation_and_survives_a_failure(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.api import demo_cache

    seed_sample(db_session)
    monkeypatch.setattr(demo_cache, "WARM_POLL_SECONDS", 0)
    seen: list[httpx.Request] = []
    web = _web(seen)
    calls = {"count": 0}

    async def flaky(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("web is starting", request=request)
        return web.handle_request(request)

    async def run() -> None:
        task = asyncio.create_task(
            demo_cache.warm_forever(app, "http://web:3000", httpx.MockTransport(flaky))
        )
        for _ in range(200):
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    opened = [request for request in seen if request.url.path == f"/o/{DEMO_ORG_SLUG}"]
    assert len(opened) == 1
    assert len(seen) == 1 + len(WARM_PAGES)


def test_the_api_starts_and_stops_the_warm_up_with_its_lifespan() -> None:
    settings = get_settings().model_copy(update={"costura_demo_warm_url": "http://127.0.0.1:9"})
    warmed = create_app(settings)

    with TestClient(warmed) as started:
        assert started.get("/live").json() == {"status": "ok"}
