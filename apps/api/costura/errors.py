"""Domain errors the API turns into HTTP responses in one place.

A domain function raises a `DomainError` subclass instead of knowing about HTTP.
`costura.main` registers one handler that answers `status` with `str(exc)` as the
detail and `code` next to it, so a router only catches an error when the same class means
a different status on that one route, or when the response must not echo the message.
`code` is a stable snake_case name per subclass; `docs/operations/errors.md` lists every
code and `tests/test_errors_doc.py` keeps the two in step.
"""


class DomainError(Exception):
    status = 422
    code = "domain_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class InvalidInput(ValueError, DomainError):
    """A request value the domain refuses: an unknown dimension, a malformed filter, a date
    range out of order, an address that is not an e-mail. Answers 422 with the message."""

    status = 422
    code = "invalid_input"


class NotFound(LookupError, DomainError):
    """The organization has no such row. Answers 404 with the message."""

    status = 404
    code = "not_found"
