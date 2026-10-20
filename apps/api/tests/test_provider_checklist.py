"""Tables outside the API that name every connector, so a new provider cannot skip one.

CONTRIBUTING.md ("Adding a provider") lists them with the rest of the checklist.
"""

import re
from pathlib import Path

import pytest

from costura.providers.registry import provider_names
from tests.test_provider_keys_doc import SECTIONS

WEB_LIB = Path(__file__).resolve().parents[2] / "web" / "src" / "lib"
TABLES = (
    ("providers.ts", "PROVIDER_LABELS"),
    ("setup.ts", "KEY_HINTS"),
    ("setup.ts", "KEY_ACCESS"),
)


def _keys(file: str, table: str) -> set[str]:
    text = (WEB_LIB / file).read_text()
    match = re.search(rf"const {table}\b[^=]*= \{{\n(.*?)\n\}};", text, flags=re.S)
    assert match, f"apps/web/src/lib/{file} has no {table} table"
    return set(re.findall(r"^  ([a-z_]+):", match.group(1), flags=re.M))


@pytest.mark.parametrize(("file", "table"), TABLES, ids=[table for _, table in TABLES])
def test_web_tables_name_every_provider(file: str, table: str) -> None:
    assert _keys(file, table) == set(provider_names()), (
        f"add the provider to {table} in apps/web/src/lib/{file}"
    )


def test_provider_keys_doc_has_a_section_per_provider() -> None:
    assert set(SECTIONS) == set(provider_names()), (
        "add a `## <Provider>` section to docs/security/provider-keys.md and to SECTIONS in "
        "tests/test_provider_keys_doc.py"
    )
