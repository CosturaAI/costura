"""The raw page every provider client yields: one response plus the exact request behind it.

Runs store `request_params` and `payload` verbatim; providers subclass `FetchedPage`
only to read their own payload shapes through `results` and `items`.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FetchedPage:
    page_index: int
    request_params: dict[str, Any]
    payload: dict[str, Any]

    @property
    def items(self) -> list[dict[str, Any]]:
        """Listing responses: the objects in `data`."""
        data = self.payload.get("data", [])
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    @property
    def results(self) -> list[dict[str, Any]]:
        return self.items
