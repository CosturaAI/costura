"""Single-purpose operational runners invoked by `just` recipes (`python -m costura.ops.<name>`).

Tenant administration lives in the API and the web app; these runners cover only what has to
happen outside a signed-in session: the scheduler process, the sync worker, retention
purge, the demo seed, the encryption key, the restricted runtime database role, the first
owner of an organization that has no members, the redacted tie-out report, and redacted
fixtures captured from stored provider pages.
"""

import signal
import sys
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager


class OperationError(Exception):
    """User-facing failure; printed to stderr with exit code 1."""


_stalled = threading.Event()


def mark_stalled() -> None:
    """Record that the coming SIGTERM comes from the worker's own stall watchdog."""
    _stalled.set()


class TerminationSignal(BaseException):
    """SIGTERM as an exception. `stalled` is true when the worker stopped itself because one
    run made no progress, which counts against that run's attempts; an operator stop does not."""

    def __init__(self, signum: int) -> None:
        super().__init__(f"terminated by signal {signum}")
        self.signum = signum
        self.stalled = _stalled.is_set()


@contextmanager
def _sigterm_as_exception() -> Generator[None]:
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum: int, _frame: object) -> None:
        raise TerminationSignal(signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def run(operation: Callable[[], int]) -> int:
    """Run `operation` with conventional exit codes: 1 on `OperationError`, 130 on Ctrl-C and
    128 + signal number on SIGTERM. Every runner logs the way the API does."""
    from costura.config import ConfigError
    from costura.telemetry import configure_logging

    try:
        with _sigterm_as_exception():
            configure_logging()
            return operation()
    except OperationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except TerminationSignal as exc:
        print(str(exc), file=sys.stderr)
        return 128 + exc.signum
