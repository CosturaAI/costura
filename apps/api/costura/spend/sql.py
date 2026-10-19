"""SQL expressions the spend readers share."""

from datetime import date, datetime

from sqlalchemy import Date, cast, func
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement


def utc_day(
    column: InstrumentedAttribute[datetime] | ColumnElement[datetime],
) -> ColumnElement[date]:
    """The UTC calendar day of a `timestamptz` column."""
    return cast(func.timezone("UTC", column), Date)
