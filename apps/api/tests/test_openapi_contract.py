"""The HTTP contract is pinned: a refactor that moves routes or schemas must not change it.

Regenerate after an intended contract change with `just api::openapi` and review the diff
of `snapshots/openapi.json`. The package version is normalized before comparison so a
release bump does not rewrite the snapshot.
"""

import json
import os
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "openapi.json"
PINNED_VERSION = "0.0.0"


def _document() -> dict:
    from costura.main import app

    app.openapi_schema = None
    document = app.openapi()
    document["info"]["version"] = PINNED_VERSION
    return document


def _dump(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def test_openapi_document_matches_the_snapshot() -> None:
    current = _document()
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(_dump(current))
    assert SNAPSHOT.exists(), "run: just api::openapi"
    expected = json.loads(SNAPSHOT.read_text())
    expected["info"]["version"] = PINNED_VERSION
    assert current == expected, (
        "the OpenAPI document changed; for an intended change run `just api::openapi` and "
        "`just web::api-types`, then review both diffs"
    )
