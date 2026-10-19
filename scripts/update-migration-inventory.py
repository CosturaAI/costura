"""Rewrite the migration inventory in apps/api/README.md from Alembic.

The API README carries the base-to-head list between
`<!-- migration-inventory:start -->` and `<!-- migration-inventory:end -->`
markers, plus prose that states the chain length ("1 revision"). This script
refreshes it after `just api::revision` creates a revision, so the
documentation test only has to catch drift.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
INVENTORIES = (API_ROOT / "README.md",)
INVENTORY_START = "<!-- migration-inventory:start -->"
INVENTORY_END = "<!-- migration-inventory:end -->"
REVISION_COUNT_PATTERN = re.compile(r"\b\d+ revisions?\b")


def inventory() -> list[str]:
    scripts = list(ScriptDirectory.from_config(Config(API_ROOT / "alembic.ini")).walk_revisions())
    return [Path(script.path).stem.split("_", 2)[2] for script in reversed(scripts)]


def render(names: list[str]) -> str:
    lines = "\n".join(f"- `{name}`" for name in names)
    return f"{INVENTORY_START}\n\n{lines}\n\n{INVENTORY_END}"


def revision_word(count: int) -> str:
    return "1 revision" if count == 1 else f"{count} revisions"


def update(path: Path, names: list[str]) -> bool:
    text = path.read_text()
    if INVENTORY_START not in text or INVENTORY_END not in text:
        raise SystemExit(f"{path} has no migration inventory markers")
    before, rest = text.split(INVENTORY_START, 1)
    _, after = rest.split(INVENTORY_END, 1)
    updated = before + render(names) + after
    updated = REVISION_COUNT_PATTERN.sub(revision_word(len(names)), updated)
    if updated == text:
        return False
    path.write_text(updated)
    return True


def main() -> int:
    names = inventory()
    changed = [path for path in INVENTORIES if update(path, names)]
    for path in changed:
        print(f"updated {path.relative_to(REPOSITORY_ROOT)} ({revision_word(len(names))})")
    if not changed:
        print(f"migration inventories already list {revision_word(len(names))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
