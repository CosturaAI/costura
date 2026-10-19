"""Month reads for one provider scope or `all`: usage, movers, series, summary,
reconcile, projection, people, activity and the generic spend query."""

import dataclasses
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from costura import accounts
from costura.api import schemas
from costura.api.deps import (
    ConcreteProviderDep,
    OrgDep,
    ProviderDep,
    RangeWindowDep,
    SessionDep,
    WindowDep,
    check_date_range,
    range_cap,
)
from costura.api.presenters.common import (
    provider_months,
)
from costura.api.presenters.query import query_csv
from costura.api.presenters.spend import (
    movers_out,
    person_out,
    projections_out,
    query_out,
    reconcile_out,
    series_csv,
    series_out,
    summary_out,
    usage_csv,
    usage_out,
)
from costura.errors import InvalidInput
from costura.spend import BREAKDOWN_DIMENSIONS, SERIES_DIMENSIONS, USAGE_DIMENSIONS, people
from costura.spend.activity import activity_report
from costura.spend.filters import (
    FILTER_OPERATORS,
    FilterClause,
    FilterOperator,
    Filters,
    normalize_filters,
)
from costura.spend.inventory import InventoryResolver
from costura.spend.invoices import invoice_total
from costura.spend.projection import stored_projections
from costura.spend.query import QuerySpec, query_spend
from costura.spend.query_contract import MEASURES
from costura.spend.reconcile import reconcile
from costura.spend.summary import comparison_for, summary
from costura.spend.usage import daily_series, movers, usage_report
from costura.spend.window import Window

router = APIRouter()

# Rises and falls together: the overview card shows up to five of each.
MOVERS_TOP = 10
SERIES_TOP_DEFAULT = 8
FORMATS = ("json", "csv")


def _one_of(values: tuple[str, ...]) -> str:
    return "^(" + "|".join(re.escape(value) for value in values) + ")$"


FormatQuery = Annotated[str, Query(pattern=_one_of(FORMATS))]
UsageByQuery = Annotated[str, Query(pattern=_one_of(USAGE_DIMENSIONS))]
SeriesByQuery = Annotated[str, Query(pattern=_one_of(SERIES_DIMENSIONS))]
BreakdownByQuery = Annotated[str, Query(pattern=_one_of(BREAKDOWN_DIMENSIONS))]
ACTIVITY_LIMIT_DEFAULT = 500
ACTIVITY_LIMIT_MAX = 2000


def query_filters(
    api_key: Annotated[str | None, Query()] = None,
    account: Annotated[str | None, Query()] = None,
    workspace: Annotated[str | None, Query()] = None,
    model: Annotated[str | None, Query()] = None,
    provider_filter: Annotated[str | None, Query(alias="provider")] = None,
    person: Annotated[str | None, Query()] = None,
    provider_account: Annotated[int | None, Query()] = None,
) -> Filters:
    return {
        name: value
        for name, value in (
            ("api_key", api_key),
            ("account", account),
            ("workspace", workspace),
            ("model", model),
            ("provider", provider_filter),
            ("person", person),
            ("provider_account", None if provider_account is None else str(provider_account)),
        )
        if value
    }


def _filter_clauses(request: Request, filters: Filters) -> Filters:
    mutable = dict(filters)
    seen: set[str] = set()
    for key, raw in request.query_params.multi_items():
        if key != "f":
            continue
        parts = raw.split(":")
        op_index = 1
        if len(parts) <= op_index + 1:
            raise InvalidInput("f must use dimension:op:value[,value]")
        dimension = ":".join(parts[:op_index])
        op = parts[op_index]
        if op not in FILTER_OPERATORS:
            raise InvalidInput(f"filter op must be one of {FILTER_OPERATORS}")
        raw_values = ":".join(parts[op_index + 1 :])
        if dimension in seen:
            raise InvalidInput(f"filter dimension {dimension!r} must not repeat")
        seen.add(dimension)
        values = (
            ()
            if op in ("exists", "not_exists") and not raw_values
            else tuple(raw_values.split(","))
        )
        mutable[dimension] = FilterClause(cast(FilterOperator, op), values)
    normalize_filters(mutable)
    return mutable


@dataclass(frozen=True)
class QueryGrouping:
    """The grouping, comparison and projection knobs shared by the query routes."""

    dimensions: str
    interval: str
    top: int
    compare: str
    projection: str
    lookback: int
    horizon: int


# Defaults exist only to keep these dependency parameters optional. FastAPI replaces them.
_NO_FILTERS: Filters = {}
_NO_GROUPING = QueryGrouping("", "day", SERIES_TOP_DEFAULT, "none", "none", 8, 4)


def query_grouping(
    dimensions: Annotated[str, Query()] = "",
    interval: Annotated[str, Query()] = "day",
    top: Annotated[int, Query()] = SERIES_TOP_DEFAULT,
    compare: Annotated[str, Query()] = "none",
    projection: Annotated[str, Query()] = "none",
    lookback: Annotated[int, Query()] = 8,
    horizon: Annotated[int, Query()] = 4,
) -> QueryGrouping:
    return QueryGrouping(dimensions, interval, top, compare, projection, lookback, horizon)


def _query_spec(
    request: Request,
    *,
    measure: str,
    start: date,
    end: date,
    grouping: QueryGrouping,
    filters: Filters,
) -> QuerySpec:
    parsed_dimensions = tuple(
        value.strip() for value in grouping.dimensions.split(",") if value.strip()
    )
    return QuerySpec(
        measure=measure,
        dimensions=parsed_dimensions,
        filters=_filter_clauses(request, filters),
        start=start,
        end=end,
        interval=grouping.interval,
        top=grouping.top,
        compare=grouping.compare,
        projection=grouping.projection,
        lookback=grouping.lookback,
        horizon=grouping.horizon,
    )


@router.get("/orgs/{org}/providers/{provider}/months", response_model=schemas.MonthsOut)
def months(session: SessionDep, org: OrgDep, provider: ProviderDep) -> schemas.MonthsOut:
    """Months with at least one cost line, newest first."""
    return schemas.MonthsOut(months=provider_months(session, org.id, provider))


@dataclass(frozen=True)
class ActivityScope:
    """The optional narrowing of the activity rows."""

    family: str | None
    provider_account: int | None
    workspace: str | None
    api_key: str | None


def activity_scope(
    family: Annotated[str | None, Query()] = None,
    provider_account: Annotated[int | None, Query()] = None,
    workspace: Annotated[str | None, Query()] = None,
    api_key: Annotated[str | None, Query()] = None,
) -> ActivityScope:
    return ActivityScope(family, provider_account, workspace, api_key)


@router.get("/orgs/{org}/activity", response_model=list[schemas.ActivityRowOut])
def activity(
    session: SessionDep,
    org: OrgDep,
    since: Annotated[date, Query()],
    until: Annotated[date, Query()],
    scope: Annotated[ActivityScope, Depends(activity_scope)],
    response: Response,
    limit: Annotated[int, Query(gt=0, le=ACTIVITY_LIMIT_MAX)] = ACTIVITY_LIMIT_DEFAULT,
) -> list[schemas.ActivityRowOut]:
    """Non-completions quantities with billed costs matched by OpenAI cost family. 422 when
    the range is reversed, outside 2000-2099 or longer than the range cap. At most `limit`
    rows; the `X-Total-Count` header carries how many matched."""
    check_date_range(since, until, longest=range_cap(org))
    report = activity_report(
        session,
        org_id=org.id,
        since=since,
        until=until,
        family=scope.family,
        provider_account_id=scope.provider_account,
        workspace_id=scope.workspace,
        api_key_id=scope.api_key,
        limit=limit,
    )
    response.headers["X-Total-Count"] = str(report.total)
    return [
        schemas.ActivityRowOut(
            family=row.family,
            unit=row.unit,
            quantity=f"{row.quantity:.8f}",
            requests=row.requests,
            billed_usd=schemas.money(row.billed_usd) or "0.00",
            cost_per_unit=schemas.money_exact(row.cost_per_unit),
        )
        for row in report.rows
    ]


@router.get("/orgs/{org}/query", response_model=schemas.QueryOut)
def spend_query(
    request: Request,
    session: SessionDep,
    org: OrgDep,
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
    measure: Annotated[str, Query()] = "billed_usd",
    grouping: Annotated[QueryGrouping, Depends(query_grouping)] = _NO_GROUPING,
    filters: Annotated[Filters, Depends(query_filters)] = _NO_FILTERS,
    format: FormatQuery = "json",
) -> schemas.QueryOut | Response:
    """A bounded date range, bucketed by day, week or month and grouped by up to three
    dimensions. Dates are inclusive; `format=csv` returns the same buckets and series in long
    form.
    """
    check_date_range(start, end, longest=range_cap(org))
    spec = _query_spec(
        request,
        measure=measure,
        start=start,
        end=end,
        grouping=grouping,
        filters=filters,
    )
    result = query_spend(session, org_id=org.id, spec=spec)
    if format == "csv":
        return query_csv(result, measure, start.isoformat(), end.isoformat(), spec.interval)
    return query_out(result)


@router.get("/orgs/{org}/queries", response_model=schemas.QueriesOut)
def spend_queries(
    request: Request,
    session: SessionDep,
    org: OrgDep,
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
    measures: Annotated[str, Query()] = "billed_usd",
    grouping: Annotated[QueryGrouping, Depends(query_grouping)] = _NO_GROUPING,
    filters: Annotated[Filters, Depends(query_filters)] = _NO_FILTERS,
) -> schemas.QueriesOut:
    """Several measures of one range, in request order, so a page can fill every series in one
    round trip. Bounds match `GET /orgs/{org}/query`. `projection` applies only to
    `billed_usd`; every other measure comes back without one.
    """
    check_date_range(start, end, longest=range_cap(org))
    names = tuple(value.strip() for value in measures.split(",") if value.strip())
    if not names:
        raise HTTPException(status_code=422, detail="measures must name at least one measure")
    if len(names) > len(MEASURES) or len(set(names)) != len(names):
        raise HTTPException(
            status_code=422,
            detail=f"measures must be distinct and at most {len(MEASURES)}",
        )
    results: list[schemas.QueryOut] = []
    for name in names:
        spec = _query_spec(
            request,
            measure=name,
            start=start,
            end=end,
            grouping=dataclasses.replace(
                grouping,
                projection=grouping.projection if name == "billed_usd" else "none",
            ),
            filters=filters,
        )
        result = query_spend(session, org_id=org.id, spec=spec)
        results.append(query_out(result))
    return schemas.QueriesOut(results=results)


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/usage", response_model=schemas.UsageOut
)
def usage(
    request: Request,
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    window: RangeWindowDep,
    month: str,
    by: UsageByQuery = "api_key",
    top: Annotated[int | None, Query(gt=0)] = None,
    filters: Annotated[Filters, Depends(query_filters)] = _NO_FILTERS,
    format: FormatQuery = "json",
) -> schemas.UsageOut | Response:
    """Tokens and allocated dollars grouped by `by`; filters narrow the lines before grouping.
    Under the `all` scope `by=provider` splits the month by connector and `?provider=` keeps
    one of them; `by=person` folds one e-mail's direct logins and qualifying Claude Code keys
    across providers and `?person=` keeps those personal lines; `by=provider_account` splits
    by the console the lines were synced from and `?provider_account=` keeps one.
    `format=csv` returns the same rows as `text/csv`.
    """
    filters = _filter_clauses(request, filters)
    report = usage_report(
        session,
        org_id=org.id,
        provider=provider,
        window=window,
        dimension=by,
        top=top,
        filters=filters,
    )
    if format == "csv":
        return usage_csv(report, f"costura-{provider}-{month}-usage-by-{by}.csv")
    return usage_out(report)


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/movers", response_model=schemas.MoversOut
)
def spend_movers(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    window: RangeWindowDep,
    month: str,
    by: UsageByQuery = "api_key",
    top: Annotated[int, Query(gt=0, le=50)] = MOVERS_TOP,
) -> schemas.MoversOut:
    """Rows of `by` ranked by how much their spend moved against the previous month (its same
    days while the month is in progress; for a `start..end` range, the range of the same length
    before it), both directions in one list; the overview splits it into rises and falls."""
    before = comparison_for(session, org_id=org.id, provider=provider, window=window, month=month)
    report = movers(
        session,
        org_id=org.id,
        provider=provider,
        window=window,
        previous=before,
        previous_month=before.start.date().isoformat()[:7],
        dimension=by,
        top=top,
    )
    return movers_out(report, before)


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/series",
    response_model=schemas.DailySeriesOut,
)
def series(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    window: RangeWindowDep,
    month: str,
    by: SeriesByQuery = "workspace",
    top: Annotated[int, Query(gt=0, le=50)] = SERIES_TOP_DEFAULT,
    filters: Annotated[Filters, Depends(query_filters)] = _NO_FILTERS,
    format: FormatQuery = "json",
) -> schemas.DailySeriesOut | Response:
    """Dollars per day, one series per group in `by` (top N, the rest summed in `other`)."""
    result = daily_series(
        session,
        org_id=org.id,
        provider=provider,
        window=window,
        dimension=by,
        top=top,
        filters=filters,
    )
    if format == "csv":
        return series_csv(result, f"costura-{provider}-{month}-daily-by-{by}.csv")
    return series_out(result, month)


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/summary",
    response_model=schemas.SummaryOut,
)
def summary_route(
    session: SessionDep, org: OrgDep, provider: ProviderDep, window: RangeWindowDep, month: str
) -> schemas.SummaryOut:
    """Headline figures: total, previous period, run rate, concentration, cache share."""
    return summary_out(
        summary(session, org_id=org.id, provider=provider, month=month, window=window)
    )


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/reconcile",
    response_model=schemas.ReconcileOut,
)
def reconcile_route(
    session: SessionDep,
    org: OrgDep,
    provider: ConcreteProviderDep,
    window: RangeWindowDep,
    month: str,
    by: BreakdownByQuery = "day",
    reported: Annotated[Decimal | None, Query()] = None,
    account: Annotated[int | None, Query()] = None,
) -> schemas.ReconcileOut:
    """Control totals are provider-specific, so the `all` scope answers 400. `?account=`
    narrows every check to one account of the provider; without it the checks add the
    provider's accounts up. `?reported=` compares with a figure typed into the request;
    without it, a calendar month compares with the invoice totals stored for it."""
    if account is not None:
        accounts.get_account(session, org.id, provider, account)
    reported_source: Literal["query", "invoice"] | None = None if reported is None else "query"
    if reported is None and window == Window.for_month(month):
        reported = invoice_total(
            session,
            org.id,
            provider,
            month,
            [a.id for a in accounts.list_accounts(session, org.id, provider)],
            account,
        )
        reported_source = None if reported is None else "invoice"
    report = reconcile(
        session,
        org_id=org.id,
        provider=provider,
        window=window,
        reported_total=reported if reported is not None else Decimal("0"),
        dimension=by,
        account_id=account,
    )
    return reconcile_out(session, org.id, report, month, reported_source=reported_source)


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/people/{email}",
    response_model=schemas.PersonOut,
)
def person(
    session: SessionDep, org: OrgDep, provider: ProviderDep, month: str, email: str
) -> schemas.PersonOut:
    """One e-mail across the providers in scope: the inventory accounts carrying it, with the
    live keys each created. 404 when no user in scope has the address. The month is part of
    the path for the web's scoped URLs only; identities do not depend on it."""
    return person_out(people.person(session, org.id, provider, email))


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/projection",
    response_model=schemas.ProjectionsOut,
)
def projection(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    window: WindowDep,
    month: str,
    by: Annotated[str, Query(pattern="^(org|workspace|model|api_key)$")] = "org",
) -> schemas.ProjectionsOut:
    """Stored month-end projections of the series of one kind; empty for a closed month or
    before the scheduler's first `project` step."""
    rows = stored_projections(session, org.id, provider, month, by)
    return projections_out(InventoryResolver(session, org.id, provider), month, by, rows)
