"""`docs/operations/errors.md` lists every `code` a `DomainError` subclass answers with, plus the
handler's own `validation_failed`; the handlers put `code` next to `detail`."""

import asyncio
import importlib
import pkgutil
import re
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import costura
from costura.errors import DomainError, InvalidInput
from costura.main import (
    HTTP_CODES,
    VALIDATION_CODE,
    domain_error_handler,
    validation_error_handler,
)

DOC = Path(__file__).resolve().parents[3] / "docs" / "operations" / "errors.md"
ENTRY = re.compile(r"^### `([a-z_]+)`\n\n- \*\*Status:\*\* (\d{3})\n", re.MULTILINE)
CODE = re.compile(r"^[a-z]+(_[a-z]+)*$")


def _subclasses() -> set[type[DomainError]]:
    for module in pkgutil.walk_packages(costura.__path__, "costura."):
        importlib.import_module(module.name)
    found: set[type[DomainError]] = set()
    pending = [DomainError]
    while pending:
        for cls in pending.pop().__subclasses__():
            found.add(cls)
            pending.append(cls)
    return found


def _documented() -> dict[str, int]:
    entries = ENTRY.findall(DOC.read_text())
    assert len(entries) == len({code for code, _ in entries}), "a code is documented twice"
    return {code: int(status) for code, status in entries}


def test_every_subclass_declares_its_own_snake_case_code() -> None:
    for cls in _subclasses():
        assert "code" in vars(cls), cls
        assert CODE.match(cls.code), cls


def test_codes_are_unique_across_subclasses() -> None:
    codes = [cls.code for cls in _subclasses()]
    assert len(codes) == len(set(codes))


def test_documented_codes_match_the_subclasses_and_their_status() -> None:
    documented = _documented()
    expected = {cls.code: cls.status for cls in _subclasses()}
    expected[VALIDATION_CODE] = 422
    expected.update({code: status for status, code in HTTP_CODES.items()})
    expected["rate_limited"] = 429
    assert documented == expected


def test_every_documented_entry_has_the_three_fields() -> None:
    text = DOC.read_text()
    for section in text.split("\n### ")[1:]:
        assert "- **Status:** " in section, section[:40]
        assert "- **Message:** " in section, section[:40]
        assert "- **Suggested action:** " in section, section[:40]


def test_domain_error_handler_answers_detail_and_code() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = asyncio.run(domain_error_handler(request, InvalidInput("op must be one of eq")))
    assert response.status_code == 422
    assert response.body == b'{"detail":"op must be one of eq","code":"invalid_input"}'


def test_domain_error_handler_refuses_other_exceptions() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    with pytest.raises(RuntimeError):
        asyncio.run(domain_error_handler(request, RuntimeError("boom")))


def test_validation_error_handler_adds_the_code_and_drops_the_input() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    error = RequestValidationError(
        [{"loc": ("query", "limit"), "msg": "bad", "type": "int_parsing", "input": "x"}]
    )
    response = asyncio.run(validation_error_handler(request, error))
    assert response.status_code == 422
    assert response.body == (
        b'{"detail":[{"loc":["query","limit"],"msg":"bad","type":"int_parsing"}],'
        b'"code":"validation_failed"}'
    )


def test_a_plain_http_refusal_carries_the_code_of_its_status(db_session: Session) -> None:
    from costura.main import app

    anonymous = TestClient(app)
    refused = anonymous.get("/api/v1/orgs/default/setup")
    assert refused.status_code == 401
    assert refused.json()["code"] == "unauthenticated"
    assert refused.headers["www-authenticate"] == "Bearer"
