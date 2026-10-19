"""`docs/security/provider-keys.md` lists every request each provider client sends, and the
non-GET requests it lists are exactly the ones the client's transport policy allows."""

import importlib
import re
from pathlib import Path

import httpx
import pytest

from costura.providers.cursor.client import allow_cursor
from costura.providers.http import get_only
from costura.providers.openrouter.client import allow_openrouter

DOC = Path(__file__).resolve().parents[3] / "docs" / "security" / "provider-keys.md"
SECTIONS = {
    "anthropic": "Anthropic",
    "claude_ai": "Claude.ai",
    "openai": "OpenAI",
    "codex": "Codex",
    "openrouter": "OpenRouter",
    "cursor": "Cursor",
    "copilot": "GitHub Copilot",
}
PREFIXES = {"openrouter": "/api/v1"}
POLICIES = {"openrouter": allow_openrouter, "cursor": allow_cursor}
REQUEST = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`]*)`")


def _shape(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _section(provider: str) -> str:
    text = DOC.read_text()
    start = text.index(f"## {SECTIONS[provider]}")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def _documented(provider: str) -> set[tuple[str, str]]:
    return {(method, _shape(path)) for method, path in REQUEST.findall(_section(provider))}


def _client_paths(provider: str) -> set[str]:
    module = importlib.import_module(f"costura.providers.{provider}.client")
    prefix = PREFIXES.get(provider, "")
    paths = set()
    for name, value in vars(module).items():
        if name.endswith("_PATH") and isinstance(value, str) and value.startswith("/"):
            full = value if value.startswith(prefix) else prefix + value
            paths.add(_shape(full))
    return paths


@pytest.mark.parametrize("provider", sorted(SECTIONS))
def test_every_client_path_is_documented(provider: str) -> None:
    documented = {path for _, path in _documented(provider)}
    missing = {
        path
        for path in _client_paths(provider)
        if path not in documented and not any(d.startswith(path + "/") for d in documented)
    }
    assert missing == set()


@pytest.mark.parametrize("provider", sorted(SECTIONS))
def test_documented_methods_match_the_transport_policy(provider: str) -> None:
    allow = POLICIES.get(provider, get_only)
    for method, path in _documented(provider):
        concrete = path.replace("{}", "x")
        assert allow(httpx.Request(method, f"https://provider.test{concrete}")), (method, path)
        if method == "GET":
            continue
        assert not get_only(httpx.Request(method, f"https://provider.test{concrete}"))
    writes = {(m, p) for m, p in _documented(provider) if m != "GET"}
    if provider not in POLICIES:
        assert writes == set()
