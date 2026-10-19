"""Seed, refresh and inspect the public sample organization.

The dataset is built in a private staging organization (`is_demo` false, no members, so the
API shows it to nobody) and published by renaming it to `demo` in one transaction. A failed
build leaves the published demo as it was; the staging organization it leaves behind is
deleted by the next refresh. One advisory lock serializes refreshes across processes.

An organization already named `demo` that is not the sample is never touched: publishing it
would expose a tenant's data to anonymous readers.
"""

import logging
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from costura.demo.build import build_dataset, span_for
from costura.demo.manifest import DATASET_VERSION, DEMO_NAME, MONTHS, PROVIDERS
from costura.errors import DomainError
from costura.models import OrganizationMember
from costura.models.organization import DEMO_ORG_SLUG, Organization
from costura.orgs import RESET_TABLES, create_org, delete_organization
from costura.scheduler_lock import lock_connection

log = logging.getLogger("costura.demo")

STAGING_PREFIX = "demo-staging-"
RETIRED_PREFIX = "demo-retired-"
# High half of the refresh advisory-lock key; distinct from the per-organization class.
DEMO_LOCK_CLASS = 0x0D30
DEMO_LOCK_KEY = DEMO_LOCK_CLASS << 32


class DemoSlugTaken(RuntimeError, DomainError):
    status = 409
    code = "demo_slug_taken"

    def __init__(self) -> None:
        super().__init__(
            f"organization {DEMO_ORG_SLUG!r} exists and is not the sample organization; "
            "costura never publishes an existing organization. Rename it (or delete it) "
            "before seeding the demo."
        )


class DemoBusy(RuntimeError, DomainError):
    status = 409
    code = "demo_busy"

    def __init__(self) -> None:
        super().__init__("another demo refresh is running; try again when it finishes")


@dataclass(frozen=True)
class DemoResult:
    organization: Organization
    # False when the published dataset was already current and nothing was written.
    seeded: bool
    start: date
    end: date
    # Rows per tenant-scoped table after the call.
    rows: dict[str, int]


@dataclass(frozen=True)
class DemoStatus:
    present: bool
    version: int | None
    current_version: int
    generated_through: date | None
    refreshed_at: datetime | None
    # Why a refresh would change the published dataset; empty when it is current.
    reasons: list[str] = field(default_factory=list)
    rows: dict[str, int] = field(default_factory=dict)
    providers: tuple[str, ...] = PROVIDERS
    abandoned: int = 0

    @property
    def current(self) -> bool:
        return not self.reasons


def demo_org(session: Session) -> Organization | None:
    return session.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))


def seed_demo(session: Session, *, today: date | None = None, **build: int) -> DemoResult:
    """Publish the sample when it is missing, empty (reset through the domain) or built from
    another dataset version; a no-op when the published version is current. Raises
    `DemoSlugTaken` for a non-sample `demo`."""
    today = today or _today()
    org = demo_org(session)
    if org is not None and not org.is_demo:
        raise DemoSlugTaken()
    if (
        org is not None
        and org.demo_dataset_version == DATASET_VERSION
        and _rows(session, org.id)["spend_cost_lines"] > 0
    ):
        span = span_for(today, build.get("months", MONTHS))
        return DemoResult(org, False, span.start, span.end, _rows(session, org.id))
    return refresh_demo(session, today=today, **build)


def refresh_demo(session: Session, *, today: date | None = None, **build: int) -> DemoResult:
    """Rebuild the sample through `today` (exclusive) and swap it in. `build` passes
    `months` and `daily_cycles` to `build_dataset`."""
    today = today or _today()
    with _refresh_lock(_engine(session)):
        if (existing := demo_org(session)) is not None and not existing.is_demo:
            raise DemoSlugTaken()
        cleanup_abandoned(session)
        staging = create_org(session, f"{STAGING_PREFIX}{secrets.token_hex(4)}", DEMO_NAME)
        staging.demo_dataset_version = DATASET_VERSION
        session.commit()
        staging_id = staging.id
        try:
            span = build_dataset(session, staging, today=today, **build)
        except BaseException:
            session.rollback()
            log.exception("demo build failed; the published sample is unchanged")
            _drop(session, staging_id)
            raise
        retired_id = _swap(session, staging_id, today)
        if retired_id is not None:
            _drop(session, retired_id)
        org = session.get(Organization, staging_id)
        assert org is not None
        return DemoResult(org, True, span.start, span.end, _rows(session, org.id))


def refresh_if_stale(session: Session, *, today: date | None = None) -> DemoResult | None:
    """The scheduler's daily hook: refresh when the published sample is missing, built from
    another version, or not generated through yesterday."""
    today = today or _today()
    status = demo_status(session, today=today)
    if status.current:
        return None
    return refresh_demo(session, today=today)


def demo_status(session: Session, *, today: date | None = None) -> DemoStatus:
    today = today or _today()
    org = demo_org(session)
    abandoned = len(_abandoned(session))
    if org is None:
        return DemoStatus(
            False, None, DATASET_VERSION, None, None, ["not seeded"], abandoned=abandoned
        )
    if not org.is_demo:
        return DemoStatus(
            True,
            None,
            DATASET_VERSION,
            None,
            None,
            [f"{DEMO_ORG_SLUG!r} belongs to a tenant and is not the sample"],
            abandoned=abandoned,
        )
    reasons = []
    if org.demo_dataset_version != DATASET_VERSION:
        reasons.append(f"dataset version {org.demo_dataset_version} is not {DATASET_VERSION}")
    rows = _rows(session, org.id)
    if not rows["spend_cost_lines"]:
        reasons.append("no cost lines")
    yesterday = today - timedelta(days=1)
    if org.demo_generated_through is None or org.demo_generated_through < yesterday:
        reasons.append(f"generated through {org.demo_generated_through}, not {yesterday}")
    return DemoStatus(
        True,
        org.demo_dataset_version,
        DATASET_VERSION,
        org.demo_generated_through,
        org.demo_refreshed_at,
        reasons,
        rows,
        abandoned=abandoned,
    )


def cleanup_abandoned(session: Session) -> int:
    """Delete staging and retired organizations a crashed refresh left behind."""
    found = _abandoned(session)
    for org_id in found:
        _drop(session, org_id)
    return len(found)


def _swap(session: Session, staging_id: int, today: date) -> int | None:
    """Retire the published sample and publish staging in one transaction. Returns the id
    of the retired organization, to delete afterwards."""
    staging = session.scalar(
        select(Organization).where(Organization.id == staging_id).with_for_update()
    )
    assert staging is not None
    current = session.scalar(
        select(Organization).where(Organization.slug == DEMO_ORG_SLUG).with_for_update()
    )
    retired_id = None
    if current is not None:
        if not current.is_demo:
            session.rollback()
            raise DemoSlugTaken()
        current.slug = f"{RETIRED_PREFIX}{secrets.token_hex(4)}"
        current.is_demo = False
        current.demo_dataset_version = current.demo_dataset_version or 0
        retired_id = current.id
        session.flush()
    staging.slug = DEMO_ORG_SLUG
    staging.is_demo = True
    staging.demo_generated_through = today - timedelta(days=1)
    staging.demo_refreshed_at = datetime.now(UTC)
    session.commit()
    return retired_id


def _abandoned(session: Session) -> list[int]:
    """Unpublished sample builds: prefixed slug, dataset version set, no members."""
    members = select(OrganizationMember.user_id).where(
        OrganizationMember.organization_id == Organization.id
    )
    return list(
        session.scalars(
            select(Organization.id)
            .where(
                Organization.is_demo.is_(False),
                Organization.demo_dataset_version.is_not(None),
                (Organization.slug.startswith(STAGING_PREFIX))
                | (Organization.slug.startswith(RETIRED_PREFIX)),
                ~members.exists(),
            )
            .order_by(Organization.id)
        )
    )


def _drop(session: Session, org_id: int) -> None:
    org = session.get(Organization, org_id)
    if org is None:
        return
    try:
        delete_organization(session, org, confirm_slug=org.slug)
    except Exception:
        session.rollback()
        log.exception("could not delete demo organization %s; the next refresh retries", org_id)


@contextmanager
def _refresh_lock(engine: Engine) -> Generator[None]:
    with lock_connection(engine) as connection:
        held = connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": DEMO_LOCK_KEY}
        ).scalar()
        if not held:
            raise DemoBusy()
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": DEMO_LOCK_KEY})
            connection.commit()


def _engine(session: Session) -> Engine:
    bind = session.get_bind()
    return bind if isinstance(bind, Engine) else bind.engine


def _rows(session: Session, org_id: int) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(
            select(func.count()).select_from(model).where(model.organization_id == org_id)
        )
        or 0
        for model in RESET_TABLES
    }


def _today() -> date:
    return datetime.now(UTC).date()
