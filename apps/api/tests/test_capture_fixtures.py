"""Captured fixtures: stored provider pages written as redacted JSON in the shape of
`tests/fixtures/<provider>/`, deterministic, with no e-mail, key or provider id left."""

import dataclasses
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from costura.ops import capture_fixtures as capture
from costura.ops.capture_fixtures import SECRET, Redactor, StoredPage, write_capture
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.normalize import cost_lines_from_payload
from costura.providers.anthropic.sync import run_cost_sync
from costura.providers.http import redact_secrets
from tests.conftest import FIXTURES, ORG_ID, load_fixture, target
from tests.support.spend import FIXTURE_END, FIXTURE_START

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _fixture_pages() -> list[StoredPage]:
    """Every synthetic fixture of every provider as if an install had stored it."""
    return [
        StoredPage(
            endpoint=f"{path.parent.name}_{path.stem}",
            page_index=0,
            request_params={},
            payload=json.loads(path.read_text()),
        )
        for path in sorted(FIXTURES.glob("*/*.json"))
    ]


def _strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in (str(key), *_strings(item))]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return [value] if isinstance(value, str) else []


def _cost_pages() -> list[StoredPage]:
    first = load_fixture("cost_report_page1.json")
    second = load_fixture("cost_report_page2.json")
    params = {
        "starting_at": "2026-08-01T00:00:00Z",
        "ending_at": "2026-08-05T00:00:00Z",
        "bucket_width": "1d",
        "limit": "31",
        "group_by[]": ["workspace_id", "description"],
    }
    return [
        StoredPage("cost_report", 0, params, first),
        StoredPage("cost_report", 1, {**params, "page": first["next_page"]}, second),
        StoredPage("workspaces", 0, {"limit": "1000"}, load_fixture("workspaces_page1.json")),
    ]


def test_no_email_key_or_known_id_survives_any_provider_fixture() -> None:
    pages = _fixture_pages()
    originals = [text for page in pages for text in _strings(page.payload)]
    redactor = Redactor()
    redacted = [text for page in pages for text in _strings(redactor.redact(page.payload))]

    emails = {match for text in originals for match in EMAIL.findall(text)}
    assert emails
    leaked = [text for text in redacted if any(email in text for email in emails)]
    assert leaked == []
    assert {match for text in redacted for match in EMAIL.findall(text)} <= {
        f"user{n}@example.com" for n in range(1, len(redactor.emails) + 1)
    }
    assert [text for text in redacted if redact_secrets(text) != text] == []
    assert not any(re.match(r"(?i)sk-|ghp_|key_[A-Za-z0-9]{16}", text) for text in redacted)
    for identifier in ("user_redacted_alice", "wrkspc_redacted_a", "proj_a", "alice-gh"):
        assert identifier not in redacted
    assert "Ada" not in redacted and "acme-inc" not in redacted
    assert redactor.secrets > 0 and redactor.ids and redactor.names and redactor.handles


def test_redaction_is_deterministic_and_keeps_numbers_dates_and_enums() -> None:
    pages = _cost_pages()
    first, second = Redactor(), Redactor()
    once = [first.redact(page.payload) for page in pages]
    again = [second.redact(page.payload) for page in pages]
    assert once == again
    assert first.summary() == second.summary()

    result = once[0]["data"][0]["results"][0]
    original = pages[0].payload["data"][0]["results"][0]
    for kept in ("amount", "model", "description", "token_type", "currency", "context_window"):
        assert result[kept] == original[kept]
    assert once[0]["data"][0]["starting_at"] == pages[0].payload["data"][0]["starting_at"]


def test_same_id_maps_to_the_same_placeholder_across_files() -> None:
    redactor = Redactor()
    payment = redactor.redact({"workspace_id": "wrkspc_01ABCdef234", "user": {"id": 42}})
    listing = redactor.redact({"data": [{"id": "wrkspc_01ABCdef234", "name": "Research"}]})
    member = redactor.redact({"owner": {"id": 42, "email": "Ada@Corp.io"}, "login": "ada"})
    again = redactor.redact({"note": "mail ada@corp.io", "serviceAccountId": "null"})

    assert payment["workspace_id"] == listing["data"][0]["id"] == "wrkspc_redacted_1"
    assert payment["user"]["id"] == member["owner"]["id"] == 1001
    assert listing["data"][0]["name"] == "Name 1"
    assert member["owner"]["email"] == "user1@example.com"
    assert member["login"] == "login-1"
    assert again == {"note": "mail user1@example.com", "serviceAccountId": "null"}


def test_values_are_classified_by_field_name_then_by_shape() -> None:
    redactor = Redactor()
    redacted = redactor.redact(
        {
            "partial_key_hint": "sk-ant-api03-...aaaa",
            "redacted_value": "sk-abc...def1",
            "access_token": "opaque",
            "avatar_url": "https://avatars.example.com/u/1",
            "organizationName": "acme-inc",
            "free": "Alice Example's sandbox",
            "pasted": "sk-live-0123456789abcdef0123",
            "ref": "proj_abc123def",
            "editor": "vscode/1.104.0",
            "client_id": "CODEX_CLI",
            "day": "2026-08-01",
            "cents": "20.18",
            "group_by[]": ["workspace_id", "description"],
            "flags": [True, None, 1.5],
        }
    )
    assert redacted == {
        "partial_key_hint": SECRET,
        "redacted_value": SECRET,
        "access_token": SECRET,
        "avatar_url": "https://example.com/redacted/1",
        "organizationName": "Name 1",
        "free": "Text 1",
        "pasted": SECRET,
        "ref": "proj_redacted_1",
        "editor": "vscode/1.104.0",
        "client_id": "CODEX_CLI",
        "day": "2026-08-01",
        "cents": "20.18",
        "group_by[]": ["workspace_id", "description"],
        "flags": [True, None, 1.5],
    }
    assert redactor.summary() == (
        "redacted: 0 e-mails, 1 ids, 1 names and logins, 1 URLs, 4 keys or tokens, "
        "1 free-text values"
    )


def test_captured_anthropic_pages_replay_through_the_client(tmp_path: Path) -> None:
    pages = _cost_pages()
    redactor = Redactor()
    write_capture(pages, tmp_path, "anthropic", redactor)
    folder = tmp_path / "anthropic"
    index = json.loads((folder / "index.json").read_text())
    assert index["provider"] == "anthropic"
    assert [entry["file"] for entry in index["pages"]] == [
        "cost_report_page1.json",
        "cost_report_page2.json",
        "workspaces_page1.json",
    ]
    by_cursor = {
        entry["request_params"].get("page"): folder / entry["file"]
        for entry in index["pages"]
        if entry["endpoint"] == "cost_report"
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = by_cursor[request.url.params.get("page")]
        return httpx.Response(200, json=json.loads(path.read_text()))

    with AnthropicAdminClient(
        admin_key="redacted", transport=httpx.MockTransport(handler), sleep=lambda _: None
    ) as client:
        replayed = [
            line
            for page in client.cost_report_pages(FIXTURE_START, FIXTURE_END)
            for line in cost_lines_from_payload(page.payload)
        ]
    expected = [
        dataclasses.replace(
            line,
            workspace_id=redactor.ids[line.workspace_id] if line.workspace_id else None,
        )
        for page in pages[:2]
        for line in cost_lines_from_payload(page.payload)
    ]
    assert replayed == expected
    listing = json.loads((folder / "workspaces_page1.json").read_text())
    workspace_ids = {item["id"] for item in listing["data"]}
    assert {line.workspace_id for line in replayed if line.workspace_id} <= workspace_ids


def test_capture_refuses_a_directory_that_already_holds_files(tmp_path: Path) -> None:
    (tmp_path / "anthropic").mkdir()
    (tmp_path / "anthropic" / "keep.json").write_text("{}")
    with pytest.raises(capture.OperationError, match="not empty"):
        write_capture(_cost_pages(), tmp_path, "anthropic", Redactor())


class _Borrowed:
    """The test session as a context manager that does not close it."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *_: object) -> None:
        return None


def test_cli_writes_the_newest_run_of_each_endpoint(
    db_session: Session,
    anthropic_client: AnthropicAdminClient,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    unit = target(db_session, ORG_ID, "anthropic")
    run_cost_sync(db_session, unit, anthropic_client, FIXTURE_START, FIXTURE_END)
    run_cost_sync(
        db_session, unit, anthropic_client, FIXTURE_START, datetime(2026, 8, 2, tzinfo=UTC)
    )
    run_inventory_sync(db_session, unit, anthropic_client)
    db_session.commit()
    monkeypatch.setattr(capture, "SessionLocal", lambda: _Borrowed(db_session))

    assert capture.main(["anthropic", str(tmp_path), "--pages", "1"]) == 0
    out = capsys.readouterr().out
    assert "redacted:" in out and "review every file" in out
    folder = tmp_path / "anthropic"
    index = json.loads((folder / "index.json").read_text())
    endpoints = [entry["endpoint"] for entry in index["pages"]]
    assert endpoints == sorted(set(endpoints))
    assert {"cost_report", "users", "api_keys", "workspaces"} <= set(endpoints)
    cost = next(entry for entry in index["pages"] if entry["endpoint"] == "cost_report")
    assert cost["request_params"]["ending_at"].startswith("2026-08-02")
    text = "".join(path.read_text() for path in folder.iterdir())
    assert not [email for email in EMAIL.findall(text) if not email.endswith("@example.com")]
    assert "sk-ant-api03" not in text and "user_redacted_alice" not in text

    assert capture.main(["anthropic", str(tmp_path)]) == 1
    assert "not empty" in capsys.readouterr().err
    assert capture.main(["openai", str(tmp_path / "none")]) == 1
    assert "no stored openai pages" in capsys.readouterr().err
    assert capture.main(["anthropic", str(tmp_path / "x"), "--org", "nope"]) == 1
    with pytest.raises(SystemExit):
        capture.main(["anthropic", str(tmp_path), "--pages", "0"])
