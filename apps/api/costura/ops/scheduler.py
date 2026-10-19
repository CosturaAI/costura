"""Scheduler process: `python -m costura.ops.scheduler [--at HH:MM] [--once]`.

Enqueues the daily sync for every connected account (`costura.scheduler.run_forever`).
The long-running process only enqueues; `python -m costura.ops.worker` executes. `--once`
enqueues and drains in this process, and exits 1 when a drained cycle failed or eligible
rows are still queued.
"""

import argparse
import logging
import sys
import threading
from collections.abc import Sequence

from costura.ops import OperationError, run

log = logging.getLogger("costura.scheduler")


def _report_cycles(results: list, slugs: dict[int, str], *, print_steps: bool) -> bool:
    """True when a cycle failed. `--once` prints each cycle for the operator at the terminal;
    the long-running processes rely on the per-step `costura.sync` log lines instead."""
    if not print_steps:
        return any(cycle.status == "failed" for cycle in results)
    any_failed = False
    for cycle in results:
        org = slugs.get(cycle.organization_id, cycle.organization_id)
        print(f"organization {org}: {cycle.status} (scheduler run {cycle.run_id})")
        if cycle.error:
            print(f"  {cycle.error}")
        for step in cycle.steps:
            print(
                f"  {step.step} {step.month or '-'} {step.status} "
                f"attempts={step.attempts} {step.duration_seconds:.1f}s {(step.detail or '')[:100]}"
            )
        any_failed = any_failed or cycle.status == "failed"
    return any_failed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.scheduler", description=__doc__)
    parser.add_argument("--at", metavar="HH:MM", default=None, help="override the daily time")
    parser.add_argument("--once", action="store_true", help="one cycle now, then exit")
    args = parser.parse_args(argv)

    def operation() -> int:

        from costura import scheduler
        from costura.config import get_settings, require_production_runtime
        from costura.db import SessionLocal
        from costura.models.organization import Organization
        from costura.ops.heartbeat import beat
        from costura.scheduler_lock import waiting_runs
        from costura.secrets import SecretKeyMissing

        settings = get_settings()
        require_production_runtime(settings)
        if settings.costura_secret_key is None:
            raise OperationError(str(SecretKeyMissing()))
        failed = False
        stop = threading.Event()

        def pulse() -> None:
            while not stop.wait(15):
                try:
                    beat("scheduler")
                except Exception:
                    log.exception("scheduler heartbeat failed")

        try:
            beat("scheduler")
        except Exception:
            log.exception("scheduler heartbeat failed")
        threading.Thread(target=pulse, name="scheduler-heartbeat", daemon=True).start()
        try:
            for results in scheduler.run_forever(
                SessionLocal, settings, at=args.at, once=args.once
            ):
                with SessionLocal() as session:
                    slugs = {o.id: o.slug for o in session.query(Organization).all()}
                failed = _report_cycles(results, slugs, print_steps=args.once) or failed
        finally:
            stop.set()
        if args.once:
            with SessionLocal() as session:
                remaining, locked = waiting_runs(session)
            if locked:
                print(f"{locked} queued runs wait for an organization another worker holds")
            if remaining > locked:
                print(f"{remaining - locked} eligible runs still queued")
                return 1
        return 1 if failed else 0

    return run(operation)


if __name__ == "__main__":
    sys.exit(main())
