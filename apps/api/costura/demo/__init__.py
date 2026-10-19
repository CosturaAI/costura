"""The sample organization: thirteen months of synthetic spend anyone can explore, session or
not.

`manifest` is the story (accounts, people, keys, streams, incidents, budgets), `payloads`
turns it into each provider's own report rows, `clients` serves those rows through the same
methods the real provider clients expose, and `build` runs the production sync cycle against
them, so raw pages, normalized lines, inventory, runs, anomalies, projections, budgets and
reconciliation come from the code paths a connected key would use. Values are hashed from
the dataset version, the day and the stream, so two builds write the same amounts and a
refresh only adds days. `lifecycle` publishes the result as `demo` (`is_demo`: public and
read-only through the API, with no members).
"""

from costura.demo.lifecycle import (
    DemoBusy,
    DemoSlugTaken,
    DemoStatus,
    demo_status,
    refresh_demo,
    refresh_if_stale,
    seed_demo,
)

__all__ = [
    "DemoBusy",
    "DemoSlugTaken",
    "DemoStatus",
    "demo_status",
    "refresh_demo",
    "refresh_if_stale",
    "seed_demo",
]
