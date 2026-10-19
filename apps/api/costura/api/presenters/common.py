"""Presenters shared by more than one router: domain rows to response schemas and the
constants they agree on. Lookups belong to the domain layer."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import (
    accounts,
    credentials,
    scheduler,
    setup_state,
)
from costura.api import schemas
from costura.config import Settings
from costura.models import (
    ProviderAccount,
    ProviderSyncRun,
    SpendCostLine,
)
from costura.models.organization import Organization
from costura.models.scheduler import SchedulerRun
from costura.providers.registry import ALL, get_spec, provider_names
from costura.run_state import latest_runs
from costura.spend.dimensions import KEY_DEFAULT_WORKSPACE, KEY_NO_MODEL
from costura.spend.inventory import InventoryResolver
from costura.spend.scope import provider_clause


def organization_out(org: Organization, role: str | None) -> schemas.OrganizationOut:
    return schemas.OrganizationOut(
        slug=org.slug,
        name=org.name,
        is_demo=org.is_demo,
        role=None if role is None else cast(schemas.Role, role),
        created_at=org.created_at,
    )


def provider_months(session: Session, org_id: int, provider: str) -> list[str]:
    month = func.to_char(func.timezone("UTC", SpendCostLine.period_start), "YYYY-MM")
    rows = session.scalars(
        select(month)
        .where(
            SpendCostLine.organization_id == org_id,
            provider_clause(SpendCostLine.provider, provider),
        )
        .group_by(month)
        .order_by(month.desc())
    ).all()
    return list(rows)


def series_label(resolver: InventoryResolver, provider: str, kind: str, series_id: str) -> str:
    if kind == "org":
        return "organization total"
    if kind == "api_key":
        return resolver.api_key_label(provider, series_id)
    if kind == "account":
        return resolver.account_label(provider, series_id)
    if kind == "team":
        return resolver.team_label(series_id)
    if kind == "workspace":
        return resolver.workspace_label(
            provider, None if series_id == KEY_DEFAULT_WORKSPACE else series_id
        )
    return "(none)" if series_id == KEY_NO_MODEL else series_id


def schedule_out(
    last: SchedulerRun | None, connected: bool, settings: Settings
) -> schemas.ScheduleOut:
    return schemas.ScheduleOut(
        last_run_id=last.id if last else None,
        last_run_at=last.started_at if last else None,
        last_finished_at=last.finished_at if last else None,
        status=last.status if last else None,
        trigger=last.trigger if last else None,
        error=last.error if last else None,
        failed_steps=[
            f"{s['step']} {s['month']}" if s.get("month") else str(s["step"])
            for s in (last.steps if last else [])
            if s.get("status") == "failed"
        ],
        next_run_at=scheduler.next_run_at(settings.costura_schedule_at) if connected else None,
        schedule_at=settings.costura_schedule_at,
    )


def account_out(
    account: ProviderAccount,
    conn: credentials.AccountConnection,
    last: SchedulerRun | None,
    settings: Settings,
    *,
    first_sync_run_id: int | None = None,
) -> schemas.AccountOut:
    cursor = (
        accounts.cursor_settings(account) if get_spec(account.provider).account_settings else None
    )
    return schemas.AccountOut(
        id=conn.account_id,
        provider=account.provider,
        label=conn.label,
        external_id=conn.external_id,
        connected=conn.connection.connected,
        source=conn.connection.source,
        key_hint=conn.connection.key_hint,
        last_validated_at=conn.connection.last_validated_at,
        last_error=conn.connection.last_error,
        schedule=schedule_out(last, conn.connection.connected, settings),
        first_sync_run_id=first_sync_run_id,
        seat_price_usd=None if cursor is None else schemas.money_exact(cursor.seat_price_usd),
        include_included_in_business=(
            None if cursor is None else cursor.include_included_in_business
        ),
        settings_effective_from=None if cursor is None else cursor.effective_from,
    )


@dataclass(frozen=True)
class ProviderState:
    """One provider of an organization as the setup and connection pages show it."""

    accounts: list[schemas.AccountOut]
    connection: credentials.Connection
    schedule: schemas.ScheduleOut
    last_sync: ProviderSyncRun | None


def provider_states(
    session: Session, settings: Settings, org_id: int, providers: Sequence[str]
) -> dict[str, ProviderState]:
    """Accounts, connection, schedule and last sync run for each provider, in a fixed number
    of queries however many accounts the organization has."""
    loaded = credentials.organization_connections(session, settings, org_id, providers)
    runs = latest_runs(session, org_id, providers)
    states: dict[str, ProviderState] = {}
    for name in providers:
        account_rows = [
            account_out(account, conn, runs.by_account.get((name, account.id)), settings)
            for account, conn in loaded.accounts[name]
        ]
        conn = loaded.environment.get(name) or provider_connection(account_rows)
        states[name] = ProviderState(
            accounts=account_rows,
            connection=conn,
            schedule=schedule_out(runs.by_provider.get(name), conn.connected, settings),
            last_sync=runs.sync_by_provider.get(name),
        )
    return states


def provider_accounts(
    session: Session, settings: Settings, org_id: int, provider: str
) -> list[schemas.AccountOut]:
    return provider_states(session, settings, org_id, [provider])[provider].accounts


def provider_list(session: Session, settings: Settings, org_id: int) -> list[schemas.ProviderOut]:
    names = provider_names()
    states = provider_states(session, settings, org_id, names)
    labels = {row.id: row.label for state in states.values() for row in state.accounts}
    result = []
    for name in names:
        spec = get_spec(name)
        state = states[name]
        conn = state.connection
        last = state.last_sync
        result.append(
            schemas.ProviderOut(
                provider=name,
                connection_type=spec.connection_type,
                label=spec.label,
                vendor=spec.vendor,
                surface=spec.surface,
                key_label=spec.key_label,
                key_prefix=spec.key_prefix,
                console_label=spec.console_label,
                console_url=spec.console_url,
                keys_console_url=spec.keys_console_url,
                env_var=spec.env_var,
                attribution=spec.attribution,
                experimental=spec.experimental,
                connected=conn.connected,
                source=conn.source,
                key_hint=conn.key_hint,
                last_validated_at=conn.last_validated_at,
                last_error=conn.last_error,
                last_run=None
                if last is None
                else labeled_run_out(last, labels.get(last.provider_account_id or 0)),
                accounts=state.accounts,
            )
        )
    return result


def account_label(session: Session, account_id: int | None) -> str | None:
    if account_id is None:
        return None
    account = session.get(ProviderAccount, account_id)
    return None if account is None else account.label


def provider_connection(account_rows: list[schemas.AccountOut]) -> credentials.Connection:
    """The provider-level summary of its accounts: connected when any is; the key fields of
    the first connected account; the newest error of any account."""
    connected = [a for a in account_rows if a.connected]
    first = connected[0] if connected else None
    errors = [a.last_error for a in account_rows if a.last_error]
    return credentials.Connection(
        connected=first is not None,
        source=first.source if first else None,
        key_hint=first.key_hint if first else None,
        last_validated_at=first.last_validated_at if first else None,
        last_error=errors[0] if errors else None,
    )


def run_out(session: Session, run: ProviderSyncRun) -> schemas.RunOut:
    return labeled_run_out(run, account_label(session, run.provider_account_id))


def labeled_run_out(run: ProviderSyncRun, label: str | None) -> schemas.RunOut:
    duration = None
    if run.finished_at is not None:
        duration = round((run.finished_at - run.started_at).total_seconds(), 3)
    return schemas.RunOut(
        id=run.id,
        provider=run.provider,
        provider_account_id=run.provider_account_id,
        provider_account_label=label,
        endpoint=run.endpoint,
        status=run.status,
        window_start=run.window_start,
        window_end=run.window_end,
        started_at=run.started_at,
        finished_at=run.finished_at,
        data_refreshed_at=run.data_refreshed_at,
        duration_seconds=duration,
        pages_fetched=run.pages_fetched,
        raw_results=run.raw_results,
        rows_upserted=run.rows_upserted,
        error=run.error,
    )


def setup_out(
    session: Session, settings: Settings, org: Organization, *, writes_enabled: bool
) -> schemas.SetupOut:
    providers = provider_list(session, settings, org.id)
    months = provider_months(session, org.id, ALL)
    first_month = months[0] if months else None
    needs_pricing = setup_state.pricing_missing(
        session, org.id, {item.provider for item in providers if item.connected}
    )
    if not any(item.connected for item in providers):
        state = "connect"
    elif needs_pricing and first_month is None:
        state = "needs_pricing"
    elif first_month is not None:
        state = "ready"
    else:
        state = "syncing"
    secret = settings.costura_secret_key
    runs = setup_state.latest_scheduler_runs(session, org.id)
    labels = {account.id: account.label for item in providers for account in item.accounts}
    missing = {
        run.provider_account_id
        for run in runs
        if run.provider_account_id is not None and run.provider_account_id not in labels
    }
    labels.update(setup_state.account_labels(session, missing))
    return schemas.SetupOut(
        state=state,
        providers=providers,
        runs=[scheduler_run_out(run, labels.get(run.provider_account_id or 0)) for run in runs],
        first_month=first_month,
        dismissed_at=org.onboarding_dismissed_at,
        writes_enabled=writes_enabled,
        worker_seen_at=setup_state.worker_seen_at(session),
        secret_ready=secret is not None and bool(secret.get_secret_value().strip()),
        needs_pricing=needs_pricing,
    )


def scheduler_run_out(run: SchedulerRun, label: str | None) -> schemas.SchedulerRunOut:
    return schemas.SchedulerRunOut(
        id=run.id,
        provider=run.provider,
        provider_account_id=run.provider_account_id,
        provider_account_label=label,
        trigger=run.trigger,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        steps=[schemas.SyncStepOut.model_validate(step) for step in run.steps],
    )
