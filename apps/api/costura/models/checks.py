"""CHECK constraints spelled from the same tuples the code reads, so a value cannot be added in
one place and refused by the database in the other."""

from collections.abc import Iterable

from sqlalchemy import CheckConstraint


def one_of(column: str, values: Iterable[str]) -> CheckConstraint:
    """`<column> IN ('a', 'b')`, named after the column (`ck_<table>_<column>`)."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=column)
