"""Spend reports to response schemas, and the CSV form the export routes share.

CSV cells are neutralized against spreadsheet formula injection; every other presenter maps a
report dataclass from `costura.spend` field by field."""

import csv
import io
import unicodedata
from decimal import Decimal
from typing import Literal

from fastapi import Response
from sqlalchemy.orm import Session

from costura import accounts
from costura.api import schemas
from costura.api.presenters.common import series_label
from costura.models import SpendProjection
from costura.providers.registry import get_spec
from costura.spend.allocation_check import AllocationCheck
from costura.spend.inventory import InventoryResolver
from costura.spend.invoices import InvoiceView
from costura.spend.money import within_cent
from costura.spend.people import Person
from costura.spend.query import QueryResult
from costura.spend.reconcile import ReconcileReport
from costura.spend.summary import Summary
from costura.spend.usage import (
    TOKEN_COLUMNS,
    DailySeries,
    MoverRow,
    MoversReport,
    UsageReport,
    UsageRow,
)
from costura.spend.window import Window

FORMULA_PREFIXES = frozenset("=+-@")


def csv_response(filename: str, header: list[str], rows: list[list[object]]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def csv_text(value: str) -> str:
    """Neutralize provider text that spreadsheet programs may interpret as a formula."""
    formula_index = 0
    while formula_index < len(value):
        char = value[formula_index]
        if not char.isspace() and not unicodedata.category(char).startswith("C"):
            break
        formula_index += 1
    if formula_index < len(value) and value[formula_index] in FORMULA_PREFIXES:
        return f"'{value}"
    return value


def usage_row_out(row: UsageRow) -> schemas.UsageRowOut:
    return schemas.UsageRowOut(
        key=row.key,
        label=row.label,
        provider=row.provider,
        details=row.details,
        amount=schemas.money(row.amount),
        share=None if row.share is None else f"{row.share:.2f}",
        tokens=row.tokens,
        total_tokens=row.total_tokens,
        web_search_requests=row.web_search_requests,
        byok_amount=schemas.money(row.byok_amount),
        person=row.person,
        provider_account_id=row.provider_account_id,
        provider_account_label=row.provider_account_label,
    )


def usage_out(report: UsageReport) -> schemas.UsageOut:
    return schemas.UsageOut(
        dimension=report.dimension,
        allocated=report.allocated,
        cost_total=schemas.money(report.cost_total),
        rows=[usage_row_out(row) for row in report.rows],
    )


def movers_out(report: MoversReport, previous: Window) -> schemas.MoversOut:
    def row(mover: MoverRow) -> schemas.MoverRowOut:
        return schemas.MoverRowOut(
            key=mover.key,
            label=mover.label,
            provider=mover.provider,
            provider_account_id=mover.provider_account_id,
            provider_account_label=mover.provider_account_label,
            amount=schemas.money(mover.amount) or "0.00",
            previous_amount=schemas.money(mover.previous_amount) or "0.00",
            delta=schemas.money(mover.delta) or "0.00",
            change_percent=(
                None if mover.change_percent is None else f"{mover.change_percent:.2f}"
            ),
            is_new=mover.is_new,
            is_gone=mover.is_gone,
        )

    return schemas.MoversOut(
        dimension=report.dimension,
        allocated=report.allocated,
        previous_month=report.previous_month,
        previous_start=previous.start.date().isoformat(),
        previous_end=previous.last_day.isoformat(),
        rows=[row(mover) for mover in report.rows],
    )


def series_out(result: DailySeries, month: str) -> schemas.DailySeriesOut:
    def money_list(values: list[Decimal]) -> list[str]:
        return [schemas.money(value) or "0.00" for value in values]

    return schemas.DailySeriesOut(
        month=month,
        dimension=result.dimension,
        source=result.source,
        days=[day.isoformat() for day in result.days],
        series=[
            schemas.SeriesOut(
                key=s.key,
                label=s.label,
                provider=s.provider,
                values=money_list(s.values),
                total=schemas.money(s.total) or "0.00",
            )
            for s in result.series
        ],
        other=None if result.other is None else money_list(result.other),
        total=money_list(result.total),
        month_total=schemas.money(sum(result.total, Decimal("0"))) or "0.00",
    )


def query_out(result: QueryResult) -> schemas.QueryOut:
    def value_list(values: list[Decimal]) -> list[str | int]:
        return [query_value_out(result.measure, value) for value in values]

    def series(values) -> list[schemas.QuerySeriesOut]:
        return [
            schemas.QuerySeriesOut(
                keys=item.keys,
                labels=item.labels,
                provider=item.provider,
                values=value_list(item.values),
                total=query_value_out(result.measure, item.total),
            )
            for item in values
        ]

    comparison = result.comparison
    return schemas.QueryOut(
        measure=result.measure,
        dimensions=list(result.dimensions),
        start=result.start.isoformat(),
        end=result.end.isoformat(),
        interval=result.interval,
        source=result.source,
        buckets=[bucket.isoformat() for bucket in result.buckets],
        series=series(result.series),
        other=None if result.other is None else value_list(result.other),
        total=value_list(result.total),
        comparison=(
            None
            if comparison is None
            else schemas.QueryComparisonOut(
                start=comparison.start.isoformat(),
                end=comparison.end.isoformat(),
                buckets=[bucket.isoformat() for bucket in comparison.buckets],
                series=series(comparison.series),
                other=None if comparison.other is None else value_list(comparison.other),
                total=value_list(comparison.total),
            )
        ),
        projection=(
            None
            if result.projection is None
            else schemas.QueryProjectionOut(
                mode=result.projection.mode,
                lookback=result.projection.lookback,
                horizon=result.projection.horizon,
                buckets=[bucket.isoformat() for bucket in result.projection.buckets],
                anchor=(
                    None
                    if result.projection.anchor is None
                    else query_value_out(result.measure, result.projection.anchor)
                ),
                values=value_list(result.projection.values),
            )
        ),
    )


def query_value_out(measure: str, value: Decimal) -> str | int:
    if measure in ("billed_usd", "byok_usd"):
        return schemas.money(value) or "0.00"
    return int(value)


def percent_out(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def summary_out(s: Summary) -> schemas.SummaryOut:
    return schemas.SummaryOut(
        complete_through=s.complete_through.isoformat() if s.complete_through else None,
        data_stale=s.data_stale,
        detection_through=s.detection_through.isoformat() if s.detection_through else None,
        duplicate_accounts=s.duplicate_accounts,
        provider_difference=schemas.money(s.provider_difference),
        currency_totals=None
        if s.currency_totals is None
        else {code: schemas.money(amount) or "0.00" for code, amount in s.currency_totals.items()},
        month=s.month,
        start=s.start.isoformat(),
        end=s.end.isoformat(),
        previous_start=s.previous_start.isoformat(),
        previous_end=s.previous_end.isoformat(),
        comparison_basis=s.comparison_basis,
        currency=s.currency,
        total=schemas.money(s.total) or "0.00",
        previous_month=s.previous_month,
        previous_total=schemas.money(s.previous_total),
        change_percent=percent_out(s.change_percent),
        days_in_month=s.days_in_month,
        days_with_data=s.days_with_data,
        last_day_with_data=(
            None if s.last_day_with_data is None else s.last_day_with_data.isoformat()
        ),
        daily_average=schemas.money(s.daily_average),
        is_current_month=s.is_current_month,
        projected_total=schemas.money(s.projected_total),
        top_keys_share=percent_out(s.top_keys_share),
        top_key_count=s.top_key_count,
        cache_read_share=percent_out(s.cache_read_share),
        tokens=s.tokens,
        allocation=allocation_out(s.allocation, s.total),
        provider_total=schemas.money(s.provider_total),
        provider_matches=s.provider_matches,
        byok_total=schemas.money(s.byok_total),
        people_total=schemas.money(s.people_total),
        people_share=percent_out(s.people_share),
    )


def allocation_out(
    check: AllocationCheck | None, cost_total: Decimal
) -> schemas.AllocationOut | None:
    if check is None:
        return None
    delta = check.delta(cost_total)
    coverage = None
    if cost_total > 0:
        coverage = f"{(check.allocated_total / cost_total * 100).quantize(Decimal('0.01')):.2f}"
    return schemas.AllocationOut(
        run_id=check.run_id,
        allocated=schemas.money(check.allocated_total) or "0.00",
        unallocated=schemas.money(check.unallocated_total) or "0.00",
        by_reason={
            reason: schemas.money(amount) or "0.00"
            for reason, amount in sorted(check.unallocated_by_reason.items())
        },
        coverage_percent=coverage,
        delta=schemas.money(delta) or "0.00",
        ok=within_cent(delta),
    )


def key_check_out(
    session: Session, org_id: int, report: ReconcileReport
) -> schemas.KeyCheckOut | None:
    check = report.key_check
    if check is None:
        return None
    resolver = InventoryResolver(session, org_id, report.provider)
    return schemas.KeyCheckOut(
        run_id=check.run_id,
        keys_compared=check.keys_compared,
        keys_off=[
            schemas.KeyDeltaOut(
                api_key_id=key.api_key_id,
                label=resolver.api_key_label(report.provider, key.api_key_id),
                provider_amount=schemas.money(key.provider_amount) or "0.00",
                allocated_amount=schemas.money(key.allocated_amount) or "0.00",
                delta=schemas.money(key.delta) or "0.00",
            )
            for key in check.keys_off
        ],
        provider_total=schemas.money(check.provider_total) or "0.00",
        allocated_total=schemas.money(check.allocated_total) or "0.00",
        ok=check.ok,
    )


def reconcile_out(
    session: Session,
    org_id: int,
    report: ReconcileReport,
    month: str,
    *,
    reported_source: Literal["query", "invoice"] | None,
) -> schemas.ReconcileOut:
    has_reported = reported_source is not None
    raw_check = None
    if report.latest_run_id is not None:
        raw_delta = report.raw_vs_normalized_delta or Decimal("0")
        raw_check = schemas.RawCheckOut(
            run_id=report.latest_run_id,
            raw_total=schemas.money(report.raw_total_latest_run) or "0.00",
            delta=schemas.money(raw_delta) or "0.00",
            ok=within_cent(raw_delta),
        )
    provider_check = None
    if report.provider_total_run_id is not None:
        provider_check = schemas.ProviderCheckOut(
            run_id=report.provider_total_run_id,
            provider_total=schemas.money(report.provider_total_latest_run) or "0.00",
            delta=schemas.money(report.provider_delta) or "0.00",
            ok=bool(report.provider_matches),
            label=get_spec(report.provider).control_total_label or "Provider-reported usage",
            derived_seat_total=schemas.money(report.derived_seat_total) or "0.00",
        )
    return schemas.ReconcileOut(
        month=month,
        currency=report.currency,
        costura_total=schemas.money(report.costura_total) or "0.00",
        costura_total_exact=schemas.money_exact(report.costura_total) or "0",
        reported_total=schemas.money(report.reported_total) if has_reported else None,
        delta=schemas.money(report.delta) if has_reported else None,
        delta_percent=(
            None
            if not has_reported or report.delta_percent is None
            else f"{report.delta_percent:.2f}"
        ),
        matches=report.matches if has_reported else None,
        reported_source=reported_source,
        breakdown_dimension=report.breakdown_dimension,
        breakdown=[
            schemas.BreakdownRowOut(label=row.label, amount=schemas.money(row.amount) or "0.00")
            for row in report.breakdown
        ],
        raw_check=raw_check,
        provider_check=provider_check,
        allocation=allocation_out(report.allocation, report.costura_total),
        key_check=key_check_out(session, org_id, report),
        key_check_supported=report.key_check_supported,
        token_totals=report.token_totals,
        activity_coverage=(
            None
            if report.activity_coverage is None
            else schemas.ActivityCoverageOut(
                covered_families=report.activity_coverage.covered_families,
                missing_families=report.activity_coverage.missing_families,
                complete=report.activity_coverage.complete,
            )
        ),
        codex_credit_check=(
            None
            if report.codex_credit_check is None
            else schemas.CodexCreditCheckOut(
                workspace_credits=schemas.money_exact(report.codex_credit_check.workspace_credits)
                or "0",
                user_credits=schemas.money_exact(report.codex_credit_check.user_credits) or "0",
                delta=schemas.money_exact(report.codex_credit_check.delta) or "0",
                missing_price_days=report.codex_credit_check.missing_price_days,
                workspace_run_id=report.codex_credit_check.workspace_run_id,
                user_run_id=report.codex_credit_check.user_run_id,
                ok=report.codex_credit_check.ok,
            )
        ),
        data_refreshed_at=report.data_refreshed_at,
        user_attributed_total=schemas.money(report.user_attributed_total),
        user_unattributed_total=schemas.money(report.user_unattributed_total),
        account_id=report.account_id,
        account_label=(
            None
            if report.account_id is None
            else accounts.get_account(session, org_id, report.provider, report.account_id).label
        ),
        accounts=[
            schemas.AccountRefOut(id=a.id, provider=a.provider, label=a.label)
            for a in accounts.list_accounts(session, org_id, report.provider)
        ],
    )


def usage_csv(report: UsageReport, filename: str) -> Response:
    header = [
        "key",
        "label",
        "provider",
        "amount",
        "share",
        *TOKEN_COLUMNS,
        "web_search_requests",
        "byok_amount",
    ]
    rows: list[list[object]] = [
        [
            csv_text(row.key or ""),
            csv_text(row.label),
            row.provider or "",
            schemas.money(row.amount) or "",
            "" if row.share is None else f"{row.share:.2f}",
            *(row.tokens[name] for name in TOKEN_COLUMNS),
            row.web_search_requests,
            schemas.money(row.byok_amount) or "",
        ]
        for row in report.rows
    ]
    return csv_response(filename, header, rows)


def series_csv(result: DailySeries, filename: str) -> Response:
    header = [
        "day",
        *(csv_text(s.label) for s in result.series),
        *(["other"] if result.other else []),
    ]
    rows: list[list[object]] = []
    for i, day in enumerate(result.days):
        row: list[object] = [day.isoformat()]
        row.extend(schemas.money(s.values[i]) for s in result.series)
        if result.other is not None:
            row.append(schemas.money(result.other[i]))
        rows.append(row)
    return csv_response(filename, header, rows)


def person_out(person: Person) -> schemas.PersonOut:
    return schemas.PersonOut(
        email=person.email,
        identities=[
            schemas.PersonIdentityOut(
                provider=i.provider,
                external_id=i.external_id,
                role=i.role,
                added_at=i.added_at,
                missing=i.missing,
                keys_created=i.keys_created,
            )
            for i in person.identities
        ],
        providers=person.providers,
    )


def projections_out(
    resolver: InventoryResolver, month: str, by: str, rows: list[SpendProjection]
) -> schemas.ProjectionsOut:
    return schemas.ProjectionsOut(
        month=month,
        by=by,
        projections=[
            schemas.ProjectionOut(
                provider=r.provider,
                series_kind=r.series_kind,
                series_id=r.series_id,
                label=series_label(resolver, r.provider, r.series_kind, r.series_id),
                as_of_day=r.as_of_day.isoformat(),
                mtd=schemas.money(r.mtd) or "0.00",
                projected_total=schemas.money(r.projected_total) or "0.00",
                low=schemas.money(r.low) or "0.00",
                high=schemas.money(r.high) or "0.00",
                currency=r.currency,
                days=[
                    schemas.ProjectedDayOut(
                        day=str(d["day"]),
                        expected=schemas.money(Decimal(str(d["expected"]))) or "0.00",
                        low=schemas.money(Decimal(str(d["low"]))) or "0.00",
                        high=schemas.money(Decimal(str(d["high"]))) or "0.00",
                        samples=int(str(d.get("samples", 0))),
                    )
                    for d in r.days
                ],
                computed_at=r.computed_at,
            )
            for r in rows
        ],
    )


def invoice_out(view: InvoiceView) -> schemas.InvoiceOut:
    row = view.row
    return schemas.InvoiceOut(
        provider=row.provider,
        account_id=row.provider_account_id,
        account_label=view.account_label,
        month=row.month,
        amount=schemas.money(row.amount) or "0.00",
        currency=row.currency,
        note=row.note,
        entered_by=view.entered_by,
        updated_at=row.updated_at,
    )
