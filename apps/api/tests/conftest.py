import json
import os
import re
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from costura.providers.runs import Target

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://costura:costura@localhost:5432/costura_test"
API_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# One database per process so two suites can run at the same time without sharing locks.
_TEST_URL = make_url(os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL))
_TEST_DATABASE = f"{_TEST_URL.database}_{os.getpid()}"
os.environ["COSTURA_ENV"] = "test"
os.environ["DATABASE_URL"] = _TEST_URL.set(database=_TEST_DATABASE).render_as_string(
    hide_password=False
)
# A test that waits on a row another session locked fails in seconds instead of hanging.
os.environ.setdefault("PGOPTIONS", "-c lock_timeout=5000")


OWNER_EMAIL = "owner@example.com"
MEMBER_EMAIL = "member@example.com"
VIEWER_EMAIL = "viewer@example.com"

# Settings and the engine are built at import time, so the environment is fixed before
# `costura` is imported anywhere in the test session.


def _ensure_test_database() -> None:
    admin = _TEST_URL.set(database="postgres").render_as_string(hide_password=False)
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": _TEST_DATABASE},
            ).scalar()
            if exists is None:
                conn.execute(text(f'CREATE DATABASE "{_TEST_DATABASE}"'))
    finally:
        engine.dispose()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """A test that reaches PostgreSQL is an integration test whether or not its module says
    so, and every other test is a unit test; `just api::test-unit` then runs without a
    database."""
    for item in items:
        if "migrated_database" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.integration)
        if item.get_closest_marker("integration") is None:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[None]:
    """PostgreSQL at head, in a database named for this process. Only tests that touch the
    database request it, so pure unit tests run without a server."""
    try:
        _ensure_test_database()
    except OperationalError as exc:
        pytest.exit(
            f"PostgreSQL is not reachable at "
            f"{_TEST_URL.render_as_string(hide_password=True)}: {exc}\n"
            "Start it with `just db::up` (or set TEST_DATABASE_URL).",
            returncode=1,
        )
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.exit(
            f"PostgreSQL is not reachable at "
            f"{make_url(os.environ['DATABASE_URL']).render_as_string(hide_password=True)}: {exc}\n"
            "Start it with `just db::up` (or set TEST_DATABASE_URL).",
            returncode=1,
        )
    finally:
        engine.dispose()
    command.upgrade(Config(API_ROOT / "alembic.ini"), "head")
    yield
    engine = create_engine(os.environ["DATABASE_URL"])
    engine.dispose()
    admin = create_engine(
        _TEST_URL.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": _TEST_DATABASE},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{_TEST_DATABASE}"'))
    finally:
        admin.dispose()


def sign_in(
    session: Session, email: str, *, owner_of: str | None = None, role_in: str | None = None
) -> str:
    """Open a session for `email` straight through `costura.auth` (no HTTP) and return the
    bearer header value; `owner_of` also makes the user owner of that organization, and
    `role_in` gives them `role` in `default` (`"member"` or `"viewer"`)."""
    from costura import auth
    from costura.orgs import get_org
    from tests.support.orgs import add_member

    signed = auth.sign_in_dev(session, email)
    if owner_of is not None:
        add_member(session, get_org(session, owner_of), signed.user, "owner")
    if role_in is not None:
        add_member(session, get_org(session, "default"), signed.user, role_in)
    session.commit()
    return f"Bearer {signed.token}"


@pytest.fixture
def owner_auth(db_session: Session) -> str:
    """`Authorization` header of `owner@example.com`, owner of the `default` organization."""
    return sign_in(db_session, OWNER_EMAIL, owner_of="default")


@pytest.fixture
def member_auth(db_session: Session, owner_auth: str) -> str:
    """`member@example.com`, a `member` of `default` next to the owner."""
    return sign_in(db_session, MEMBER_EMAIL, role_in="member")


@pytest.fixture
def viewer_auth(db_session: Session, owner_auth: str) -> str:
    """`viewer@example.com`, a read-only `viewer` of `default` next to the owner."""
    return sign_in(db_session, VIEWER_EMAIL, role_in="viewer")


@pytest.fixture
def client(owner_auth: str) -> Iterator[TestClient]:
    """The app as seen by the signed-in owner of `default`."""
    from costura.main import app

    with TestClient(app, headers={"Authorization": owner_auth}) as test_client:
        yield test_client


@pytest.fixture
def db_session(migrated_database: None) -> Iterator[Session]:
    """A session on the test database; the tables are emptied before each test, so the
    next test, not this one, pays for the cleanup."""
    import costura.models  # noqa: F401
    from costura.db import Base, SessionLocal, get_engine

    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        # Every test works under the `default` organization (id 1 after RESTART IDENTITY).
        conn.execute(text("INSERT INTO organizations (slug, name) VALUES ('default', 'Default')"))
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


ORG_ID = 1


@pytest.fixture(autouse=True)
def fresh_rate_limits() -> Iterator[None]:
    """The limiter counts per process; each test starts with empty windows."""
    from costura.api.ratelimit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def no_optional_provider_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider keys from the repo-root `.env` are absent unless a test opts in."""
    from costura.config import get_settings

    monkeypatch.setattr(get_settings(), "openrouter_admin_key", None)
    monkeypatch.setattr(get_settings(), "openai_admin_key", None)
    monkeypatch.setattr(get_settings(), "cursor_api_key", None)
    monkeypatch.setattr(get_settings(), "claude_ai_api_key", None)
    monkeypatch.setattr(get_settings(), "codex_admin_key", None)
    monkeypatch.setattr(get_settings(), "costura_operator_email", None)
    monkeypatch.setattr(get_settings(), "costura_operator_secret", None)


def request_session(db_session: Session) -> Callable[[], Iterator[Session]]:
    """A `get_session` override on the test's session that keeps production's unit of work:
    a fresh identity map per request, commit when the route returns, rollback when it raises.
    Background syncs read through sessions of their own, so they see only committed rows."""

    def override() -> Iterator[Session]:
        db_session.expire_all()
        try:
            yield db_session
            db_session.commit()
        except BaseException:
            db_session.rollback()
            raise

    return override


@pytest.fixture
def org_id(db_session: Session) -> int:
    """Id of the `default` organization inserted by `db_session`."""
    return ORG_ID


SAMPLE_TODAY = date(2026, 9, 15)


def seed_sample(session: Session, today: date = SAMPLE_TODAY):
    """The published sample organization shrunk to two months and one sync cycle: the same
    accounts, inventory and stories in a few seconds instead of the full build."""
    from costura.demo import seed_demo

    return seed_demo(session, today=today, months=2, daily_cycles=0)


def account_of(session: Session, org_id: int, provider: str) -> int:
    """Id of the provider's default account in `org_id`, created on first use."""
    from costura import accounts

    account = accounts.ensure_default_account(session, org_id, provider)
    session.commit()
    return account.id


def target(session: Session, org_id: int, provider: str) -> Target:
    """Sync target for the provider's default account in `org_id`."""
    from costura.providers.runs import Target

    return Target(org_id=org_id, account_id=account_of(session, org_id, provider))


@pytest.fixture
def query_synced(db_session: Session, anthropic_client: object) -> None:
    """Anthropic cost, usage, inventory, and allocation used by range-query tests."""
    from costura.providers.anthropic.inventory import run_inventory_sync
    from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
    from costura.spend.allocate import run_allocation
    from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START

    unit = target(db_session, ORG_ID, "anthropic")
    run_cost_sync(db_session, unit, anthropic_client, FIXTURE_START, FIXTURE_END)
    run_usage_sync(db_session, unit, anthropic_client, FIXTURE_START, FIXTURE_END)
    run_inventory_sync(db_session, unit, anthropic_client)
    run_allocation(db_session, ORG_ID, "anthropic", AUGUST)


def load_fixture(name: str, provider: str = "anthropic") -> dict:
    return json.loads((FIXTURES / provider / name).read_text())


def cursor_fixture_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/teams/members"):
        name = "members.json"
    elif path.endswith("/teams/filtered-usage-events"):
        body = json.loads(request.content or b"{}")
        name = "usage_page2.json" if body.get("page") == 2 else "usage_page1.json"
    elif path.endswith("/teams/spend"):
        name = "spend.json"
    else:
        return httpx.Response(404, json={"error": f"unexpected path {path}"})
    return httpx.Response(200, json=load_fixture(name, "cursor"))


def copilot_fixture_handler(request: httpx.Request) -> httpx.Response:
    """Serve the GitHub fixtures: one seat page, the same usage day for any date, one AI
    credit page per known login (empty for others), and a public profile per login."""
    params = httpx.QueryParams(request.url.query)
    path = request.url.path
    if path.endswith("/copilot/billing/seats"):
        name = "seats_page1.json"
    elif path.endswith("/settings/billing/usage"):
        name = "usage_day.json"
    elif path.endswith("/settings/billing/budgets"):
        name = "budgets.json"
    elif path.endswith("/settings/billing/ai_credit/usage"):
        login = params.get("user") or ""
        candidate = FIXTURES / "copilot" / f"ai_credit_{login.replace('-gh', '')}.json"
        if not candidate.exists():
            return httpx.Response(200, json={"usageItems": []})
        name = candidate.name
    elif path.startswith("/users/"):
        login = path.rsplit("/", 1)[-1]
        candidate = FIXTURES / "copilot" / f"user_{login.replace('-gh', '')}.json"
        if not candidate.exists():
            return httpx.Response(404, json={"message": "Not Found"})
        name = candidate.name
    else:
        return httpx.Response(404, json={"message": f"unexpected path {path}"})
    return httpx.Response(200, json=load_fixture(name, "copilot"))


def openrouter_fixture_handler(request: httpx.Request) -> httpx.Response:
    """Serve the OpenRouter fixtures the way the management API answers a personal account:
    keys by offset, one workspaces page, 403 on workspace members, 404 on organization
    members, and the analytics query by presence of `dimensions` in the JSON body."""
    params = httpx.QueryParams(request.url.query)
    path = request.url.path
    if path.endswith("/analytics/query"):
        body = json.loads(request.content or b"{}")
        name = "analytics_query_page1.json" if body.get("dimensions") else "analytics_total.json"
    elif path.endswith("/analytics/meta"):
        name = "analytics_meta.json"
    elif path.endswith("/key"):
        auth = request.headers.get("authorization", "")
        name = "key_regular.json" if auth.endswith("regular") else "key.json"
    elif path.endswith("/keys"):
        name = "keys_page2.json" if params.get("offset") not in (None, "0") else "keys_page1.json"
    elif path.endswith("/organization/members"):
        error = load_fixture("organization_members_error.json", "openrouter")
        return httpx.Response(404, json=error)
    elif path.endswith("/members"):
        error = load_fixture("workspace_members_error.json", "openrouter")
        return httpx.Response(403, json=error)
    elif path.endswith("/workspaces"):
        name = "workspaces.json"
    elif path.endswith("/credits"):
        name = "credits.json"
    else:
        message = f"unexpected path {path}"
        return httpx.Response(404, json={"error": {"message": message, "code": 404}})
    return httpx.Response(200, json=load_fixture(name, "openrouter"))


def openai_fixture_handler(request: httpx.Request) -> httpx.Response:
    """Serve the OpenAI fixtures the way the Admin API pages them: `page` cursors on the
    reports, `after` on the listings, the costs report by its `group_by`, and per-project
    listings by project id. `proj_old` (archived) answers 403 on its keys and users."""
    params = httpx.QueryParams(request.url.query)
    path = request.url.path
    cursor = params.get("page")
    if path.endswith("/organization/costs"):
        group_by = params.get_list("group_by")
        if not group_by:
            name = "costs_total.json"
        elif "line_item" in group_by:
            name = "costs_page2.json" if cursor == "page_costs_2" else "costs_page1.json"
        else:
            name = "costs_by_key.json"
    elif path.endswith("/organization/usage/completions"):
        name = (
            "usage_completions_page2.json"
            if cursor == "page_usage_2"
            else "usage_completions_page1.json"
        )
    elif match := re.fullmatch(r".*/organization/usage/([^/]+)", path):
        family = match.group(1)
        name = {
            "images": "usage_images_page1.json",
            "embeddings": "usage_embeddings.json",
            "moderations": "usage_moderations.json",
            "audio_speeches": "usage_audio_speeches.json",
            "audio_transcriptions": "usage_audio_transcriptions.json",
            "vector_stores": "usage_vector_stores.json",
            "code_interpreter_sessions": "usage_code_interpreter.json",
        }.get(family, "")
        if not name:
            return httpx.Response(404, json={"error": {"message": f"unexpected family {family}"}})
    elif path.endswith("/organization/projects"):
        name = "projects_page1.json"
    elif path.endswith("/organization/users"):
        name = "users_page1.json"
    else:
        match = re.fullmatch(r".*/organization/projects/([^/]+)/(api_keys|users)", path)
        if match is None:
            message = f"unexpected path {path}"
            return httpx.Response(404, json={"error": {"message": message}})
        project_id, listing = match.groups()
        if project_id == "proj_old":
            return httpx.Response(403, json=load_fixture("project_forbidden.json", "openai"))
        name = f"project_{listing}_{project_id}.json"
    return httpx.Response(200, json=load_fixture(name, "openai"))


def anthropic_fixture_handler(request: httpx.Request) -> httpx.Response:
    """Serve the JSON fixtures the way the Admin API pages them.

    Report endpoints use the opaque `page` cursor; listing endpoints use `after_id`. The
    archived workspace answers 404 on its members listing, as the live API can. The usage
    report rejects more than 5 `group_by[]`, honours the `context_window[]` and
    `inference_geos[]` filters, and returns null for dimensions that are not grouped.
    """
    params = httpx.QueryParams(request.url.query)
    path = request.url.path
    cursor = params.get("page")
    after_id = params.get("after_id")
    if path.endswith("/cost_report"):
        if not params.get_list("group_by[]"):
            name = "cost_report_total_page1.json"
        else:
            name = "cost_report_page2.json" if cursor == "page_cost_2" else "cost_report_page1.json"
    elif path.endswith("/usage_report/messages"):
        group_by = params.get_list("group_by[]")
        if len(group_by) > 5:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Cannot specify more than 5 `group_by[]` dimensions.",
                    },
                },
            )
        name = "usage_report_page2.json" if cursor == "page_usage_2" else "usage_report_page1.json"
        return httpx.Response(200, json=_filter_usage(load_fixture(name), params, group_by))
    elif path.endswith("/organizations/me"):
        # The organization behind the key labels the account; a key ending in `-second`
        # opens another organization so tests can connect two accounts of one provider.
        key = request.headers.get("x-api-key", "")
        name = "organization_second.json" if key.endswith("-second") else "organization_me.json"
    elif path.endswith("/organizations/workspaces"):
        name = "workspaces_page2.json" if after_id else "workspaces_page1.json"
    elif path.endswith("/organizations/users"):
        name = "users_page1.json"
    elif path.endswith("/organizations/api_keys"):
        name = "api_keys_page2.json" if after_id else "api_keys_page1.json"
    elif path.endswith("/members"):
        workspace_id = path.split("/")[-2]
        candidate = FIXTURES / "anthropic" / f"workspace_members_{workspace_id}_page1.json"
        if not candidate.exists():
            return httpx.Response(404, json={"error": {"message": "workspace not found"}})
        name = candidate.name
    else:
        return httpx.Response(404, json={"error": f"unexpected path {path}"})
    return httpx.Response(200, json=load_fixture(name))


def _filter_usage(payload: dict, params: httpx.QueryParams, group_by: list[str]) -> dict:
    windows = params.get_list("context_window[]")
    geos = params.get_list("inference_geos[]")
    for bucket in payload.get("data", []):
        kept = []
        for result in bucket.get("results", []):
            if windows and result.get("context_window") not in windows:
                continue
            if geos and result.get("inference_geo") not in geos:
                continue
            for dimension in ("context_window", "inference_geo", "account_id"):
                if group_by and dimension not in group_by:
                    result[dimension] = None
            kept.append(result)
        bucket["results"] = kept
    return payload


@pytest.fixture
def anthropic_client():
    from costura.providers.anthropic.client import AnthropicAdminClient

    with AnthropicAdminClient(
        admin_key="sk-ant-admin01-test",
        transport=httpx.MockTransport(anthropic_fixture_handler),
        sleep=lambda _: None,
    ) as client:
        yield client


@pytest.fixture
def openai_client():
    from costura.providers.openai.client import OpenAIAdminClient

    with OpenAIAdminClient(
        admin_key="sk-admin-test",
        transport=httpx.MockTransport(openai_fixture_handler),
        sleep=lambda _: None,
    ) as client:
        yield client


@pytest.fixture
def openrouter_client():
    from costura.providers.openrouter.client import OpenRouterManagementClient

    with OpenRouterManagementClient(
        management_key="sk-or-v1-test",
        transport=httpx.MockTransport(openrouter_fixture_handler),
        sleep=lambda _: None,
    ) as client:
        yield client


@pytest.fixture
def cursor_client():
    from costura.providers.cursor.client import CursorAdminClient

    with CursorAdminClient(
        api_key="key_test",
        transport=httpx.MockTransport(cursor_fixture_handler),
        sleep=lambda _: None,
    ) as client:
        yield client


@pytest.fixture
def claude_ai_client():
    from costura.providers.claude_ai.client import (
        COST_REPORT_PATH,
        USER_COST_REPORT_PATH,
        USER_USAGE_REPORT_PATH,
        USERS_PATH,
        ClaudeAiAnalyticsClient,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        cost_payload = (
            "cost_report.json"
            if request.url.params.get_list("group_by[]")
            else "cost_total_report.json"
        )
        name = {
            COST_REPORT_PATH: cost_payload,
            USER_COST_REPORT_PATH: "user_cost_report.json",
            USER_USAGE_REPORT_PATH: "user_usage_report.json",
            USERS_PATH: "users.json",
        }[request.url.path]
        return httpx.Response(200, json=json.loads((FIXTURES / "claude_ai" / name).read_text()))

    with ClaudeAiAnalyticsClient(
        api_key="redacted", transport=httpx.MockTransport(handler), sleep=lambda _: None
    ) as client:
        yield client


@pytest.fixture
def copilot_client():
    from costura.providers.copilot.client import GitHubBillingClient

    with GitHubBillingClient(
        token="ghp_test",
        org="acme-inc",
        transport=httpx.MockTransport(copilot_fixture_handler),
        sleep=lambda _: None,
    ) as client:
        yield client
