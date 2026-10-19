"""The August fixture window every spend test reads against."""

from datetime import UTC, datetime

from costura.spend.window import Window

AUGUST = Window.for_month("2026-08")
FIXTURE_START = datetime(2026, 8, 1, tzinfo=UTC)
FIXTURE_END = datetime(2026, 8, 5, tzinfo=UTC)
