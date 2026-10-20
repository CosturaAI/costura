"""The provider registry: every connector's `ProviderSpec`, and the `all` scope.

Credentials, the scheduler, the API scope and the reconcile control total dispatch through
`PROVIDERS[name]`. Adding a provider starts with a package under providers/ with its own
`spec.py` and one entry here; CONTRIBUTING.md ("Adding a provider") lists the rest.
"""

from collections.abc import Iterator, Sequence

from costura.providers.anthropic.spec import ANTHROPIC_SPEC
from costura.providers.claude_ai.spec import CLAUDE_AI_SPEC
from costura.providers.codex.spec import CODEX_SPEC
from costura.providers.copilot.spec import COPILOT_SPEC
from costura.providers.cursor.spec import CURSOR_SPEC
from costura.providers.openai.spec import OPENAI_SPEC
from costura.providers.openrouter.spec import OPENROUTER_SPEC
from costura.providers.spec import AccountInfo, NotManagementKey, ProviderSpec

ALL = "all"

PROVIDERS: dict[str, ProviderSpec] = {
    ANTHROPIC_SPEC.name: ANTHROPIC_SPEC,
    CLAUDE_AI_SPEC.name: CLAUDE_AI_SPEC,
    CODEX_SPEC.name: CODEX_SPEC,
    OPENROUTER_SPEC.name: OPENROUTER_SPEC,
    OPENAI_SPEC.name: OPENAI_SPEC,
    CURSOR_SPEC.name: CURSOR_SPEC,
    COPILOT_SPEC.name: COPILOT_SPEC,
}


def provider_names() -> tuple[str, ...]:
    return tuple(PROVIDERS)


def find_spec(provider: str) -> ProviderSpec | None:
    """The spec of one connector; None for the `all` scope or an unknown name."""
    return PROVIDERS.get(provider)


def get_spec(provider: str) -> ProviderSpec:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise KeyError(f"unknown provider {provider!r}; known: {', '.join(PROVIDERS)}") from None


def provider_origin(provider: str) -> str:
    """Surface label derived from the connector slug."""
    return get_spec(provider).surface


def specs() -> Iterator[ProviderSpec]:
    return iter(PROVIDERS.values())


def resolve_scope(scope: str) -> Sequence[str]:
    """Concrete provider names for a URL scope: `all` expands to every registered provider."""
    return provider_names() if scope == ALL else (get_spec(scope).name,)


__all__ = [
    "ALL",
    "PROVIDERS",
    "AccountInfo",
    "NotManagementKey",
    "ProviderSpec",
    "get_spec",
    "provider_names",
    "provider_origin",
    "resolve_scope",
    "specs",
]
