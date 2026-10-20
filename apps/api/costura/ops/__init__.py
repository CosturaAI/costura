"""Single-purpose operational runners invoked by `just` recipes (`python -m costura.ops.<name>`).

Tenant administration lives in the API and the web app; these runners cover only what has to
happen outside a signed-in session: the scheduler process, the sync worker, retention
purge, the demo seed, the encryption key, the restricted runtime database role, the first
owner of an organization that has no members, and the redacted tie-out report.
"""

import signal
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager


class OperationError(Exception):
    """User-facing failure; printed to stderr with exit code 1."""


class TerminationSignal(BaseException):
    def __init__(self, signum: int) -> None:
        super().__init__(f"terminated by signal {signum}")
        self.signum = signum


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
