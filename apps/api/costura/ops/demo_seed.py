"""The read-only sample organization: `python -m costura.ops.demo_seed [seed|refresh|status]`.

`seed` (the default) publishes the sample when it is missing or from another dataset
version, and writes nothing when it is current. `refresh` rebuilds it through today and swaps
it in. `status` prints what is published and exits 1 when a refresh would change it. None of
them needs COSTURA_SECRET_KEY or a provider key. An organization named `demo` that is not the
sample is never published: the command fails and leaves it alone. `--today YYYY-MM-DD` builds
or checks the sample as of another day, which makes a build reproducible (the seeded browser
suite uses it). `status --json` prints the same fields as one JSON object with the same exit code.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

from costura.ops import OperationError, run

if TYPE_CHECKING:
    from costura.demo import DemoStatus


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.demo_seed", description=__doc__)
    parser.add_argument("action", nargs="?", choices=("seed", "refresh", "status"), default="seed")
    parser.add_argument("--today", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    parser.add_argument(
        "--json", action="store_true", help="with status: print one JSON object instead of text"
    )
    args = parser.parse_args(argv)
    if args.json and args.action != "status":
        parser.error("--json applies to status")

    def operation() -> int:
        from costura.db import SessionLocal
        from costura.demo import DemoBusy, DemoSlugTaken, demo_status, refresh_demo, seed_demo

        with SessionLocal() as session:
            if args.action == "status":
                return _print_status(demo_status(session, today=args.today), as_json=args.json)
            try:
                result = (seed_demo if args.action == "seed" else refresh_demo)(
                    session, today=args.today
                )
            except (DemoSlugTaken, DemoBusy) as exc:
                raise OperationError(str(exc)) from exc
        slug = result.organization.slug
        if not result.seeded:
            print(f"demo organization {slug} is current; nothing written")
            return 0
        print(
            f"published demo organization {slug} ({result.organization.name}): "
            f"[{result.start.isoformat()}, {result.end.isoformat()})"
        )
        for table, count in result.rows.items():
            if count:
                print(f"  {table}: {count}")
        return 0

    return run(operation)


def _print_status(status: DemoStatus, *, as_json: bool = False) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "present": status.present,
                    "version": status.version,
                    "current_version": status.current_version,
                    "generated_through": (
                        status.generated_through.isoformat() if status.generated_through else None
                    ),
                    "refreshed_at": (
                        status.refreshed_at.isoformat() if status.refreshed_at else None
                    ),
                    "providers": list(status.providers),
                    "abandoned": status.abandoned,
                    "rows": dict(status.rows),
                    "current": status.current,
                    "reasons": list(status.reasons),
                }
            )
        )
        return 0 if status.current else 1
    print(f"present: {'yes' if status.present else 'no'}")
    print(f"dataset version: {status.version} (current {status.current_version})")
    print(f"generated through: {status.generated_through or '-'}")
    print(f"refreshed at: {status.refreshed_at.isoformat() if status.refreshed_at else '-'}")
    print(f"providers: {', '.join(status.providers)}")
    if status.abandoned:
        print(f"abandoned builds: {status.abandoned} (the next refresh deletes them)")
    for table, count in status.rows.items():
        if count:
            print(f"  {table}: {count}")
    if status.current:
        print("current")
        return 0
    for reason in status.reasons:
        print(f"stale: {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
