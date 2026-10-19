"""Provider-neutral bookkeeping for a sync: the `provider_sync_runs` row, the raw pages and the
replace-style upsert of normalized rows.

Report syncs (`run_report`) and inventory listings (`run_listing`, `mark_missing`) share the
same shape for every provider: one run row per endpoint per call, pages committed as they
arrive so a failure halfway leaves the raw evidence in place, normalized rows written in one
transaction at the end.
"""

from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from costura.db import Base
from costura.models import (
    ProviderApiKey,
    ProviderInventoryEvent,
    ProviderModelSeen,
    ProviderReportPage,
    ProviderSyncRun,
    ProviderUser,
    ProviderWorkspaceMember,
    SpendActivityLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.providers.http import ProviderApiError, stored_exception_text
from costura.providers.upsert import upsert_rows
from costura.spend.sql import utc_day


@dataclass(frozen=True)
class Target:
    """Where a sync writes: one provider account of one organization. Every run, page and
    normalized row carries both ids."""

    org_id: int
    account_id: int


class Page(Protocol):
    """One response page plus the exact query that produced it."""

    @property
    def page_index(self) -> int: ...

    @property
    def request_params(self) -> dict[str, Any]: ...

    @property
    def payload(self) -> dict[str, Any]: ...

    @property
    def results(self) -> list[dict[str, Any]]:
        """Report endpoints: the result rows on the page."""
        ...

    @property
    def items(self) -> list[dict[str, Any]]:
        """Listing endpoints: the objects on the page."""
        ...


@dataclass
class SyncSummary:
    endpoint: str
    run_id: int
    window_start: datetime
    window_end: datetime
    pages_fetched: int = 0
    raw_results: int = 0
    rows_upserted: int = 0
    data_refreshed_at: datetime | None = None


@dataclass
class InventorySummary:
    endpoint: str
    run_id: int
    pages_fetched: int = 0
    items: int = 0
    rows_upserted: int = 0
    skipped_workspaces: list[str] = field(default_factory=list)


def open_run(
    session: Session,
    target: Target,
    provider: str,
    endpoint: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> ProviderSyncRun:
    now = datetime.now(UTC)
    run = ProviderSyncRun(
        organization_id=target.org_id,
        provider_account_id=target.account_id,
        provider=provider,
        endpoint=endpoint,
        window_start=start or now,
        window_end=end or now,
    )
    session.add(run)
    session.commit()
    return run


def store_page(session: Session, run: ProviderSyncRun, page: Page) -> None:
    session.add(
        ProviderReportPage(
            organization_id=run.organization_id,
            sync_run_id=run.id,
            provider=run.provider,
            endpoint=run.endpoint,
            page_index=page.page_index,
            request_params=page.request_params,
            payload=page.payload,
        )
    )
    session.commit()


def close_run(
    session: Session,
    run: ProviderSyncRun,
    *,
    pages_fetched: int,
    raw_results: int,
    rows_upserted: int,
    error: BaseException | None,
) -> None:
    run.status = "failed" if error else "succeeded"
    run.finished_at = datetime.now(UTC)
    run.pages_fetched = pages_fetched
    run.raw_results = raw_results
    run.rows_upserted = rows_upserted
    if error:
        run.error = stored_exception_text(error)
    session.commit()


def run_report[LineT](
    session: Session,
    target: Target,
    provider: str,
    *,
    endpoint: str,
    pages: Callable[[], Iterator[Page]],
    start: datetime,
    end: datetime,
    normalize: Callable[[Any], list[LineT]],
    aggregate: Callable[[list[LineT]], list[LineT]],
    upsert: Callable[[Session, Target, Sequence[LineT], int], int],
    replaces: Sequence[type[SpendCostLine] | type[SpendUsageLine] | type[SpendActivityLine]] = (),
) -> SyncSummary:
    run = open_run(session, target, provider, endpoint, start=start, end=end)
    summary = SyncSummary(endpoint=endpoint, run_id=run.id, window_start=start, window_end=end)
    try:
        lines: list[LineT] = []
        for page in pages():
            store_page(session, run, page)
            summary.pages_fetched += 1
            summary.raw_results += len(page.results)
            lines.extend(normalize(page))
            watermark = _payload_watermark(page.payload)
            if watermark is not None:
                summary.data_refreshed_at = (
                    watermark
                    if summary.data_refreshed_at is None
                    else min(summary.data_refreshed_at, watermark)
                )
        aggregated = aggregate(lines)
        summary.rows_upserted = upsert(session, target, aggregated, run.id)
        for model in replaces:
            _delete_unreported(session, model, run, start, end)
        run.data_refreshed_at = summary.data_refreshed_at
        if any(getattr(line, "model", None) and hasattr(line, "amount") for line in aggregated):
            refresh_observed_models(session, target.org_id, provider, end)
    except BaseException as exc:
        session.rollback()
        close_run(
            session,
            run,
            pages_fetched=summary.pages_fetched,
            raw_results=summary.raw_results,
            rows_upserted=0,
            error=exc,
        )
        raise
    close_run(
        session,
        run,
        pages_fetched=summary.pages_fetched,
        raw_results=summary.raw_results,
        rows_upserted=summary.rows_upserted,
        error=None,
    )
    return summary


def _delete_unreported(
    session: Session,
    model: type[SpendCostLine] | type[SpendUsageLine] | type[SpendActivityLine],
    run: ProviderSyncRun,
    start: datetime,
    end: datetime,
) -> None:
    earlier = select(ProviderSyncRun.id).where(
        ProviderSyncRun.organization_id == run.organization_id,
        ProviderSyncRun.provider_account_id == run.provider_account_id,
        ProviderSyncRun.provider == run.provider,
        ProviderSyncRun.endpoint == run.endpoint,
        ProviderSyncRun.id != run.id,
    )
    session.execute(
        delete(model).where(
            model.organization_id == run.organization_id,
            model.provider_account_id == run.provider_account_id,
            model.provider == run.provider,
            model.period_start >= start,
            model.period_start < end,
            model.sync_run_id.in_(earlier),
        )
    )


def _payload_watermark(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("data_refreshed_at")
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def refresh_observed_models(session: Session, org_id: int, provider: str, as_of: datetime) -> int:
    """Refresh the provider's observed model ids and trailing 30-day billed amount."""
    session.flush()
    day = utc_day(SpendCostLine.period_start)
    rows = session.execute(
        select(
            SpendCostLine.model,
            func.min(day),
            func.max(day),
            func.coalesce(
                func.sum(SpendCostLine.amount).filter(
                    SpendCostLine.period_start >= as_of - timedelta(days=30)
                ),
                0,
            ),
        )
        .where(
            SpendCostLine.organization_id == org_id,
            SpendCostLine.provider == provider,
            SpendCostLine.model.is_not(None),
            SpendCostLine.period_start < as_of,
        )
        .group_by(SpendCostLine.model)
    ).all()
    if not rows:
        return 0
    values = [
        {
            "organization_id": org_id,
            "provider": provider,
            "model": model,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "last_amount_30d": amount,
        }
        for model, first_seen, last_seen, amount in rows
    ]
    statement = insert(ProviderModelSeen).values(values)
    excluded = statement.excluded
    session.execute(
        statement.on_conflict_do_update(
            index_elements=("organization_id", "provider", "model"),
            set_={
                "first_seen": func.least(ProviderModelSeen.first_seen, excluded.first_seen),
                "last_seen": func.greatest(ProviderModelSeen.last_seen, excluded.last_seen),
                "last_amount_30d": excluded.last_amount_30d,
                "updated_at": func.now(),
            },
        )
    )
    return len(values)


def run_listing[RecordT](
    session: Session,
    target: Target,
    provider: str,
    *,
    endpoint: str,
    pages: Callable[[], Iterator[Page]],
    normalize: Callable[[dict[str, Any]], list[RecordT]],
    model: type[Base],
    constraint: str,
    replace_columns: tuple[str, ...],
    missing_exclude: Any = None,
) -> InventorySummary:
    """One complete listing: upsert every record, then mark rows the listing no longer returns
    as `missing_since` (rows matching `missing_exclude` belong to another listing and stay)."""
    run = open_run(session, target, provider, endpoint)
    summary = InventorySummary(endpoint=endpoint, run_id=run.id)
    try:
        records: list[RecordT] = []
        for page in pages():
            store_page(session, run, page)
            summary.pages_fetched += 1
            summary.items += len(page.items)
            records.extend(normalize(page.payload))
        before = _inventory_state(session, model, target, provider)
        summary.rows_upserted = write_records(
            session,
            model,
            records,
            target,
            run.id,
            constraint=constraint,
            replace_columns=replace_columns,
        )
        mark_missing(session, model, target, provider, run.id, exclude=missing_exclude)
        _record_changes(session, model, target, provider, run.id, before)
    except BaseException as exc:
        session.rollback()
        close_inventory_run(session, run, summary, exc)
        raise
    close_inventory_run(session, run, summary, None)
    return summary


@dataclass(frozen=True)
class ScopedListingOptions:
    """The optional knobs of a scoped inventory run."""

    skippable_statuses: frozenset[int] = frozenset()
    page_factory: Callable[..., Page] | None = None
    missing_exclude: Callable[[Sequence[str]], Any] | None = None


def run_scoped_listing[RecordT](
    session: Session,
    target: Target,
    provider: str,
    *,
    endpoint: str,
    scopes: Sequence[str],
    pages: Callable[[str], Iterator[Page]],
    normalize: Callable[[dict[str, Any], str], list[RecordT]],
    scope_param: str,
    model: type[Base],
    constraint: str,
    replace_columns: tuple[str, ...],
    options: ScopedListingOptions | None = None,
) -> InventorySummary:
    """One run over a list of scopes (workspaces, projects): each page is stored with the scope
    id stamped onto its request params, a scope whose status is in `skippable_statuses` is
    recorded and excluded from the missing-row pass, and every other failure fails the run."""

    chosen = options or ScopedListingOptions()
    run = open_run(session, target, provider, endpoint)
    summary = InventorySummary(endpoint=endpoint, run_id=run.id)
    try:
        records: list[RecordT] = []
        page_index = 0
        for scope_id in scopes:
            try:
                for page in pages(scope_id):
                    params = {**page.request_params, scope_param: scope_id}
                    stamped = (
                        chosen.page_factory(
                            page_index=page_index, request_params=params, payload=page.payload
                        )
                        if chosen.page_factory is not None
                        else page
                    )
                    store_page(session, run, stamped)
                    page_index += 1
                    summary.pages_fetched += 1
                    summary.items += len(page.items)
                    records.extend(normalize(page.payload, scope_id))
            except ProviderApiError as exc:
                if exc.status_code not in chosen.skippable_statuses:
                    raise
                summary.skipped_workspaces.append(scope_id)
        before = _inventory_state(session, model, target, provider)
        summary.rows_upserted = write_records(
            session,
            model,
            records,
            target,
            run.id,
            constraint=constraint,
            replace_columns=replace_columns,
        )
        exclude = (
            chosen.missing_exclude(summary.skipped_workspaces)
            if chosen.missing_exclude is not None
            else None
        )
        mark_missing(session, model, target, provider, run.id, exclude=exclude)
        _record_changes(session, model, target, provider, run.id, before)
        close_inventory_run(session, run, summary, None)
    except BaseException as exc:
        session.rollback()
        close_inventory_run(session, run, summary, exc)
        raise
    return summary


def close_inventory_run(
    session: Session, run: ProviderSyncRun, summary: InventorySummary, error: BaseException | None
) -> None:
    close_run(
        session,
        run,
        pages_fetched=summary.pages_fetched,
        raw_results=summary.items,
        rows_upserted=summary.rows_upserted,
        error=error,
    )


def mark_missing(
    session: Session,
    model: type[Base],
    target: Target,
    provider: str,
    run_id: int,
    *,
    exclude: Any = None,
) -> int:
    """Rows of this account the run did not return are marked missing; rows of the other
    accounts of the provider are another listing's and stay."""
    table = model.__table__
    statement = (
        update(model)
        .where(
            table.c.organization_id == target.org_id,
            table.c.provider_account_id == target.account_id,
            table.c.provider == provider,
            table.c.sync_run_id != run_id,
            table.c.missing_since.is_(None),
        )
        .values(missing_since=datetime.now(UTC))
    )
    if exclude is not None:
        statement = statement.where(exclude)
    # ty reads Result as read-only here; DELETE/UPDATE returns CursorResult.
    return session.execute(statement).rowcount  # ty: ignore[unresolved-attribute]


def write_records(
    session: Session,
    model: type[Base],
    records: Sequence[Any],
    target: Target,
    run_id: int,
    *,
    constraint: str,
    replace_columns: tuple[str, ...],
) -> int:
    rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        row = asdict(record)
        row["organization_id"] = target.org_id
        row["provider_account_id"] = target.account_id
        row["sync_run_id"] = run_id
        # A listing can repeat an item across pages; the last occurrence wins.
        key = tuple(row[column] for column in key_columns(model))
        rows[key] = row
    return upsert_rows(
        session,
        model,
        list(rows.values()),
        constraint=constraint,
        replace_columns=replace_columns,
        extra_set={"missing_since": None},
    )


ENTITY_KINDS: dict[type[Base], str] = {ProviderApiKey: "api_key", ProviderUser: "user"}

InventoryState = dict[str, tuple[str | None, bool]]


def _inventory_state(
    session: Session, model: type[Base], target: Target, provider: str
) -> InventoryState | None:
    if model not in ENTITY_KINDS:
        return None
    table = model.__table__
    status = table.c.status if "status" in table.c else None
    rows = session.execute(
        select(
            table.c.external_id,
            status if status is not None else table.c.external_id,
            table.c.missing_since,
        ).where(
            table.c.organization_id == target.org_id,
            table.c.provider_account_id == target.account_id,
            table.c.provider == provider,
        )
    )
    return {
        external_id: (state if status is not None else None, missing is not None)
        for external_id, state, missing in rows
    }


def _record_changes(
    session: Session,
    model: type[Base],
    target: Target,
    provider: str,
    run_id: int,
    before: InventoryState | None,
) -> None:
    after = _inventory_state(session, model, target, provider)
    if before is None or after is None or not before:
        return
    kind = ENTITY_KINDS[model]
    for external_id, (status, missing) in after.items():
        previous = before.get(external_id)
        if previous is None:
            event, from_status = "created", None
        elif previous[1] and not missing:
            event, from_status = "returned", previous[0]
        elif not previous[1] and missing:
            event, from_status = "missing", previous[0]
        elif previous[0] != status:
            event, from_status = "status_changed", previous[0]
        else:
            continue
        session.add(
            ProviderInventoryEvent(
                organization_id=target.org_id,
                provider_account_id=target.account_id,
                provider=provider,
                entity_kind=kind,
                external_id=external_id,
                event=event,
                from_status=from_status,
                to_status=status,
                sync_run_id=run_id,
            )
        )


def key_columns(model: type[Base]) -> tuple[str, ...]:
    if model is ProviderWorkspaceMember:
        return ("provider", "workspace_external_id", "user_external_id")
    return ("provider", "external_id")
