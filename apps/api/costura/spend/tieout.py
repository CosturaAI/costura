"""A tie-out report that can leave the organization: per provider and month, whether each check
passed and by how many percent it missed, never an amount, key, workspace or e-mail.

It answers "do Costura's numbers match the provider?" for someone who may not see the bill,
such as a maintainer reading an issue. `costura.ops.tieout` prints it.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import accounts
from costura.models import SpendCostLine
from costura.providers.registry import provider_names
from costura.spend.invoices import invoice_total
from costura.spend.money import to_percent, within_cent
from costura.spend.reconcile import reconcile
from costura.spend.summary import summary
from costura.spend.window import Window

PASS = "pass"
FAIL = "fail"
NONE = "-"


@dataclass(frozen=True)
class TieOutRow:
    provider: str
    month: str
    provider_check: str
    provider_delta_percent: Decimal | None
    stored_rows: str
    attribution: str
    allocated_percent: Decimal | None
    invoice_check: str
    invoice_delta_percent: Decimal | None
    people_percent: Decimal | None


def months_with_cost(session: Session, org_id: int, provider: str) -> list[str]:
    """Calendar months (UTC) with at least one cost line, newest first."""
    month = func.to_char(func.timezone("UTC", SpendCostLine.period_start), "YYYY-MM")
    return list(
        session.scalars(
            select(month)
            .where(SpendCostLine.organization_id == org_id, SpendCostLine.provider == provider)
            .group_by(month)
            .order_by(month.desc())
        )
    )


def _verdict(ok: bool | None) -> str:
    if ok is None:
        return NONE
    return PASS if ok else FAIL


def _percent(delta: Decimal | None, base: Decimal | None) -> Decimal | None:
    if delta is None or base is None or base == 0:
        return None
    return to_percent(delta / base * 100)


def tieout_row(session: Session, org_id: int, provider: str, month: str) -> TieOutRow:
    window = Window.for_month(month)
    invoiced = invoice_total(
        session,
        org_id,
        provider,
        month,
        [a.id for a in accounts.list_accounts(session, org_id, provider)],
    )
    report = reconcile(
        session,
        org_id=org_id,
        provider=provider,
        window=window,
        reported_total=invoiced if invoiced is not None else Decimal("0"),
    )
    month_summary = summary(session, org_id=org_id, provider=provider, month=month)
    raw_delta = report.raw_vs_normalized_delta
    allocation = report.allocation
    allocated = None
    if allocation is not None and report.costura_total > 0:
        allocated = to_percent(allocation.allocated_total / report.costura_total * 100)
    return TieOutRow(
        provider=provider,
        month=month,
        provider_check=_verdict(report.provider_matches),
        provider_delta_percent=_percent(report.provider_delta, report.provider_total_latest_run),
        stored_rows=_verdict(None if raw_delta is None else within_cent(raw_delta)),
        attribution=_verdict(
            None if allocation is None else within_cent(allocation.delta(report.costura_total))
        ),
        allocated_percent=allocated,
        invoice_check=_verdict(None if invoiced is None else report.matches),
        invoice_delta_percent=None if invoiced is None else report.delta_percent,
        people_percent=month_summary.people_share,
    )


def tieout_report(session: Session, org_id: int, months: int) -> list[TieOutRow]:
    """The newest `months` calendar months with cost lines, for every provider with any."""
    rows: list[TieOutRow] = []
    for provider in provider_names():
        for month in months_with_cost(session, org_id, provider)[:months]:
            rows.append(tieout_row(session, org_id, provider, month))
    return rows


COLUMNS = (
    ("provider", "provider"),
    ("month", "month"),
    ("provider total", "provider_check"),
    ("delta %", "provider_delta_percent"),
    ("stored rows", "stored_rows"),
    ("attribution", "attribution"),
    ("allocated %", "allocated_percent"),
    ("invoice", "invoice_check"),
    ("invoice delta %", "invoice_delta_percent"),
    ("people %", "people_percent"),
)


def render(rows: list[TieOutRow]) -> str:
    """A fixed-width plain-text table, safe to paste into an issue."""
    cells = [[title for title, _ in COLUMNS]]
    for row in rows:
        values = []
        for _, attribute in COLUMNS:
            value = getattr(row, attribute)
            values.append(NONE if value is None else str(value))
        cells.append(values)
    widths = [max(len(line[index]) for line in cells) for index in range(len(COLUMNS))]
    lines = ["  ".join(text.ljust(widths[i]) for i, text in enumerate(line)) for line in cells]
    return "\n".join(line.rstrip() for line in lines)
