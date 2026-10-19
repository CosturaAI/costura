"""Scalar parsing shared by the provider normalizers.

Every function raises `NormalizeError` with the field name when the value has the wrong shape,
so a provider payload change fails the page instead of silently writing a wrong row. The
provider modules keep thin wrappers where their messages differ. `loose_text` is the one
lenient reader: listing fields that may be any type and count only when non-empty text.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from costura.providers.lines import NormalizeError, parse_timestamp


def optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizeError(f"{field} is not a string: {value!r}")
    return value or None


def unix_seconds(value: Any, *, field: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NormalizeError(f"{field} is not Unix seconds: {value!r}")
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise NormalizeError(f"{field} is outside the supported range: {value!r}") from exc


def rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise NormalizeError(f"{field} is missing")
    return value


def required_text(value: Any, *, field: str) -> str:
    found = optional_text(value, field=field)
    if found is None:
        raise NormalizeError(f"{field} is missing")
    return found


def text_or(value: Any, *, field: str, default: str | None = None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        raise NormalizeError(f"{field} is not a string: {value!r}")
    return value or default


def loose_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def count(value: Any, *, field: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizeError(f"{field} is not an integer: {value!r}")
    return value


def optional_timestamp(value: Any, *, field: str) -> datetime | None:
    return None if value is None else parse_timestamp(value, field=field)


def nested_id(value: Any) -> str | None:
    return loose_text(value.get("id")) if isinstance(value, dict) else None


def optional_decimal(value: Any, *, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise NormalizeError(f"{field} is not a number: {value!r}")
    try:
        return Decimal(str(value))
    except ArithmeticError as exc:
        raise NormalizeError(f"{field} is not a number: {value!r}") from exc


def optional_day(value: Any, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizeError(f"{field} is not a date: {value!r}")
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise NormalizeError(f"{field} is not a date: {value!r}") from exc
    return datetime(day.year, day.month, day.day, tzinfo=UTC)
