"""The `[start, end)` UTC window every spend reader, detector and report is asked about."""

import calendar
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from costura.errors import InvalidInput


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @classmethod
    def for_month(cls, month: str) -> Window:
        """`YYYY-MM` -> `[first day 00:00Z, first day of next month 00:00Z)`."""
        year_text, _, month_text = month.partition("-")
        year, month_number = int(year_text), int(month_text)
        if not 1 <= month_number <= 12:
            raise InvalidInput(f"invalid month: {month!r}")
        start = datetime(year, month_number, 1, tzinfo=UTC)
        days = calendar.monthrange(year, month_number)[1]
        return cls(start=start, end=start + timedelta(days=days))

    @classmethod
    def for_dates(cls, start: date, end: date) -> Window:
        if start > end:
            raise InvalidInput(f"start {start} is after end {end}")
        begin = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
        return cls(start=begin, end=begin + timedelta(days=(end - start).days + 1))

    @property
    def last_day(self) -> date:
        return self.end.date() - timedelta(days=1)

    def preceding(self) -> Window:
        return Window(start=self.start - (self.end - self.start), end=self.start)

    def month_parts(self) -> list[Window]:
        parts: list[Window] = []
        cursor = self.start
        while cursor < self.end:
            first = cursor.replace(day=1)
            month_end = Window.for_month(f"{first.year}-{first.month:02d}").end
            parts.append(Window(start=cursor, end=min(month_end, self.end)))
            cursor = parts[-1].end
        return parts

    def days(self) -> Iterator[date]:
        cursor = self.start.date()
        while datetime.combine(cursor, datetime.min.time(), tzinfo=UTC) < self.end:
            yield cursor
            cursor += timedelta(days=1)


def previous_window(window: Window, month: str) -> Window:
    if window == Window.for_month(month):
        return Window.for_month(previous_month(month))
    return window.preceding()


def comparison_window(window: Window, month: str, *, through: date | None = None) -> Window:
    before = previous_window(window, month)
    if through is None or window != Window.for_month(month):
        return before
    return Window.for_dates(before.start.date(), shift_month(through, -1))


def shift_month(value: date, months: int) -> date:
    """The same day `months` later, clamped to the last day of the landing month."""
    index = value.year * 12 + value.month - 1 + months
    year, zero_month = divmod(index, 12)
    month = zero_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def previous_month(month: str) -> str:
    """`YYYY-MM` of the month before `month`."""
    year, number = (int(part) for part in month.split("-"))
    if number == 1:
        return f"{year - 1}-12"
    return f"{year}-{number - 1:02d}"
