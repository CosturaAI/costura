"""Print the tie-out report of one organization: per provider and month, pass or fail and the
percent missed for each check, with no amount, key, workspace or e-mail in the output.

`python -m costura.ops.tieout --org default --months 3`. The output is safe to paste into a
public issue when the organization's own figures are confidential. `--json` prints the same
rows as one JSON object for scripts and agents.
"""

import argparse
import json
from collections.abc import Sequence
from decimal import Decimal

from costura.db import SessionLocal
from costura.ops import OperationError, run
from costura.orgs import UnknownOrganization, get_org
from costura.spend.tieout import COLUMNS, TieOutRow, render, tieout_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.tieout", description=__doc__)
    parser.add_argument("--org", default="default", help="organization slug (default: default)")
    parser.add_argument(
        "--months", type=int, default=3, help="newest months with cost per provider (default 3)"
    )
    parser.add_argument(
        "--json", action="store_true", help="print one JSON object instead of the text table"
    )
    args = parser.parse_args(argv)
    if args.months < 1:
        parser.error("--months must be 1 or more")

    def operation() -> int:
        with SessionLocal() as session:
            try:
                org = get_org(session, args.org)
            except UnknownOrganization as exc:
                raise OperationError(f"no organization {args.org!r}") from exc
            rows = tieout_report(session, org.id, args.months)
        if args.json:
            print(render_json(rows, organization=args.org, months=args.months))
            return 0
        if not rows:
            print(f"no cost lines in organization {args.org!r}")
            return 0
        print(render(rows))
        return 0

    return run(operation)


def render_json(rows: list[TieOutRow], *, organization: str, months: int) -> str:
    """The report as one JSON object: the same columns as the text table, verdicts as strings,
    percentages as numbers, missing values as null, and no amount anywhere."""
    return json.dumps(
        {
            "organization": organization,
            "months": months,
            "rows": [
                {attribute: _json_value(getattr(row, attribute)) for _, attribute in COLUMNS}
                for row in rows
            ],
        }
    )


def _json_value(value: str | Decimal | None) -> str | float | None:
    if isinstance(value, Decimal):
        return float(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
