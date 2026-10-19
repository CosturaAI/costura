"""Documentation contracts that must follow executable repository state."""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

API_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = API_ROOT.parents[1]
INVENTORY_PATTERN = re.compile(r"^- `([0-9a-f]{12}_[a-z0-9_]+)`$", re.MULTILINE)
INVENTORY_START = "<!-- migration-inventory:start -->"
INVENTORY_END = "<!-- migration-inventory:end -->"
# Prose that states the size of the chain: "17 revisions", "Alembic's 17 revisions".
REVISION_COUNT_PATTERN = re.compile(r"\b(\d+) revisions?\b")


def _documented_inventory(path: Path) -> list[str]:
    text = path.read_text()
    inventory = text.split(INVENTORY_START, 1)[1].split(INVENTORY_END, 1)[0]
    return INVENTORY_PATTERN.findall(inventory)


def _alembic_inventory() -> list[str]:
    scripts = list(ScriptDirectory.from_config(Config(API_ROOT / "alembic.ini")).walk_revisions())
    base_to_head = reversed(scripts)
    return [Path(script.path).stem.split("_", 2)[2] for script in base_to_head]


def test_documented_migration_inventories_match_alembic() -> None:
    actual = _alembic_inventory()

    assert actual, "the migration chain is empty"
    assert _documented_inventory(API_ROOT / "README.md") == actual


def test_documented_revision_counts_match_alembic() -> None:
    expected = str(len(_alembic_inventory()))
    path = API_ROOT / "README.md"
    counts = REVISION_COUNT_PATTERN.findall(path.read_text())
    assert counts, f"{path} states no revision count"
    assert set(counts) == {expected}, f"{path} states {counts}, chain has {expected}"


# Documents that describe how to run the project today.
LIVING_DOCS = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "apps/api/README.md",
    "apps/web/README.md",
    "skills/costura/SKILL.md",
)
RECIPE_REFERENCE = re.compile(r"\bjust ([a-z]+)::([a-z][a-z0-9-]*)")
RECIPE_DEFINITION = re.compile(r"^([a-z][a-z0-9-]*)(?:\s[^:]*)?:", re.MULTILINE)
REMOVED_COMMAND = re.compile(r"\buv run costura\b|`costura (?:org|sync|secret|demo|scheduler)\b")


def _living_docs() -> list[Path]:
    return sorted(path for pattern in LIVING_DOCS for path in REPOSITORY_ROOT.glob(pattern))


def _recipes(module: str) -> set[str]:
    path = REPOSITORY_ROOT / ".just" / f"{module}.just"
    return set(RECIPE_DEFINITION.findall(path.read_text())) if path.exists() else set()


def test_living_docs_cite_only_existing_just_recipes() -> None:
    missing = [
        f"{path.relative_to(REPOSITORY_ROOT)}: just {module}::{recipe}"
        for path in _living_docs()
        for module, recipe in RECIPE_REFERENCE.findall(path.read_text())
        if recipe not in _recipes(module)
    ]
    assert missing == []


PATH_REFERENCE = re.compile(r"`((?:apps|docs|scripts|\.github)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`")


def test_living_docs_cite_only_existing_paths() -> None:
    missing = [
        f"{path.relative_to(REPOSITORY_ROOT)}: {cited}"
        for path in _living_docs()
        for cited in PATH_REFERENCE.findall(path.read_text())
        if not (REPOSITORY_ROOT / cited).exists()
    ]
    assert missing == []


def test_living_docs_cite_no_removed_command_line() -> None:
    stale = [
        str(path.relative_to(REPOSITORY_ROOT))
        for path in _living_docs()
        if REMOVED_COMMAND.search(path.read_text())
    ]
    assert stale == []
