"""Write the provider responses an install stored as redacted JSON fixtures.

`python -m costura.ops.capture_fixtures anthropic ./captured --org default --pages 3` reads,
for every endpoint of the provider, the pages of the newest sync run in
`provider_report_pages`: the responses exactly as the provider sent them. Each page is
written to `<out_dir>/<provider>/<endpoint>_page<N>.json` in the shape of
`tests/fixtures/<provider>/`, with `index.json` naming the endpoint and request of each file.
It makes no provider call, reads no key and uploads nothing.

Redaction is on by default and deterministic within one capture: an e-mail becomes
`userN@example.com`, a provider id keeps its prefix and becomes `<prefix>_redacted_N`, so the
same id carries the same placeholder in every file, names become `Name N`, keys and tokens
become `[redacted]`, and unknown free text becomes `Text N`. Numbers, dates, model names,
enums and the structure stay as received.
"""

import argparse
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.db import SessionLocal
from costura.models import ProviderReportPage
from costura.ops import OperationError, run
from costura.orgs import UnknownOrganization, get_org
from costura.providers.http import redact_secrets
from costura.providers.registry import provider_names

DEFAULT_PAGES = 3
SECRET = "[redacted]"
REVIEW_REMINDER = (
    "review every file before sharing it: redaction works from field names and value shapes "
    "and can miss a personal value the provider puts in an unexpected field"
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ][0-9:.]+(Z|[+\-]\d{2}:?\d{2})?)?$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][+\-]?\d+)?$")
_PREFIXED_ID = re.compile(r"^([A-Za-z]{2,12})([_\-])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,}$")
_ID_PREFIX = re.compile(r"^([A-Za-z]{2,12})([_\-])")
_TOKEN = re.compile(r"^[A-Za-z0-9#][A-Za-z0-9_.:+/\-]{0,79}$")
_KEY_PREFIX = re.compile(r"(?i)^(?:bearer\s|sk[-_]|rk[-_]|key_|crsr_|gh[pousr]_|github_pat_)")

# Values the normalizers branch on: models, enums, units, line items, report dimensions.
KEPT = frozenset(
    {
        "model",
        "models",
        "description",
        "line_item",
        "sku",
        "product",
        "unit_type",
        "cost_type",
        "token_type",
        "service_tier",
        "context_window",
        "inference_geo",
        "currency",
        "kind",
        "type",
        "object",
        "status",
        "role",
        "workspace_role",
        "plan_type",
        "speed",
        "scope",
        "report_kind",
        "group",
        "group_by",
        "group_by[]",
        "budget_scope",
        "budget_product_sku",
        "provider_name",
        "last_activity_editor",
        "client_id",
    }
)
CURSORS = frozenset({"page", "next_page", "cursor", "next_cursor", "after", "before"})
EMPTY_IDS = frozenset({"", "null", "none", "None", "undefined"})
ID_NAMES = frozenset({"id", "hash", "uuid"})
SECRET_PARTS = ("secret", "password", "credential", "authorization", "cookie", "hint", "redacted")
SECRET_NAMES = frozenset({"key", "api_key", "label", "token"})
NAME_NAMES = frozenset(
    {"name", "nickname", "company", "location", "bio", "blog", "title", "organization"}
)
HANDLE_NAMES = frozenset(
    {
        "login",
        "username",
        "handle",
        "slug",
        "user",
        "actor",
        "owner",
        "assignee",
        "created_by",
        "creator",
        "member",
    }
)


def field_name(key: str) -> str:
    """`organizationName` and `_costura_login` as `organization_name` and `login`."""
    return _CAMEL.sub("_", key.removeprefix("_costura_")).lower()


@dataclass
class Redactor:
    """One capture's placeholders. The same input value always maps to the same placeholder,
    in the order values are first met, so a capture of the same pages is byte-identical."""

    emails: dict[str, str] = field(default_factory=dict)
    ids: dict[str, str] = field(default_factory=dict)
    int_ids: dict[int, int] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    handles: dict[str, str] = field(default_factory=dict)
    urls: dict[str, str] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    secrets: int = 0

    def redact(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {self._emails_in(str(k)): self.redact(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(item, key) for item in value]
        if isinstance(value, bool) or value is None or isinstance(value, float):
            return value
        if isinstance(value, int):
            return self._int_id(value) if _is_id(field_name(key)) else value
        if isinstance(value, str):
            return self._string(value, field_name(key))
        return value

    def summary(self) -> str:
        counts = (
            (len(self.emails), "e-mails"),
            (len(self.ids) + len(self.int_ids), "ids"),
            (len(self.names) + len(self.handles), "names and logins"),
            (len(self.urls), "URLs"),
            (self.secrets, "keys or tokens"),
            (len(self.texts), "free-text values"),
        )
        return "redacted: " + ", ".join(f"{count} {label}" for count, label in counts)

    def _string(self, value: str, name: str) -> str:
        if _EMAIL.fullmatch(value):
            return self._email(value)
        if name in KEPT:
            return self._scrubbed(value)
        if _is_id(name) or name in CURSORS:
            return value if value in EMPTY_IDS else self._id(value)
        if (
            name in SECRET_NAMES
            or name.endswith(("_token", "_key"))
            or any(part in name for part in SECRET_PARTS)
        ):
            return self._secret(value)
        if "email" in name or name in HANDLE_NAMES:
            return self._placeholder(self.handles, value, "login-{n}")
        if name.endswith("url") or name in {"href", "link"}:
            return self._placeholder(self.urls, value, "https://example.com/redacted/{n}")
        if name in NAME_NAMES or name.endswith("_name"):
            return self._placeholder(self.names, value, "Name {n}")
        return self._free(value)

    def _free(self, value: str) -> str:
        if _KEY_PREFIX.match(value):
            return self._secret(value)
        scrubbed = self._scrubbed(value)
        if scrubbed != value or _DATE.match(value) or _NUMBER.match(value):
            return scrubbed
        if _PREFIXED_ID.match(value):
            return self._id(value)
        if _TOKEN.match(value):
            return value
        return self._placeholder(self.texts, value, "Text {n}")

    def _scrubbed(self, value: str) -> str:
        cleaned = redact_secrets(value)
        if cleaned != value:
            self.secrets += 1
        return self._emails_in(cleaned)

    def _emails_in(self, value: str) -> str:
        return _EMAIL.sub(lambda match: self._email(match.group(0)), value)

    def _email(self, value: str) -> str:
        return self._placeholder(self.emails, value.lower(), "user{n}@example.com")

    def _id(self, value: str) -> str:
        if "@" in value:
            return self._emails_in(value)
        prefix = _ID_PREFIX.match(value)
        template = f"{prefix.group(1)}{prefix.group(2)}redacted_{{n}}" if prefix else "redacted_{n}"
        return self._placeholder(self.ids, value, template)

    def _int_id(self, value: int) -> int:
        return self.int_ids.setdefault(value, 1000 + len(self.int_ids) + 1)

    def _secret(self, _value: str) -> str:
        self.secrets += 1
        return SECRET

    @staticmethod
    def _placeholder(table: dict[str, str], value: str, template: str) -> str:
        if value not in table:
            table[value] = template.format(n=len(table) + 1)
        return table[value]


def _is_id(name: str) -> bool:
    return name in ID_NAMES or name.endswith(("_id", "_ids"))


@dataclass(frozen=True)
class StoredPage:
    endpoint: str
    page_index: int
    request_params: dict[str, Any]
    payload: dict[str, Any]


def newest_pages(
    session: Session, org_id: int, provider: str, *, per_endpoint: int
) -> list[StoredPage]:
    """The first `per_endpoint` pages of the newest run of every endpoint that stored any."""
    newest = (
        select(ProviderReportPage.endpoint, func.max(ProviderReportPage.sync_run_id))
        .where(
            ProviderReportPage.organization_id == org_id,
            ProviderReportPage.provider == provider,
        )
        .group_by(ProviderReportPage.endpoint)
    )
    pages: list[StoredPage] = []
    for endpoint, run_id in sorted(session.execute(newest).all()):
        rows = session.scalars(
            select(ProviderReportPage)
            .where(ProviderReportPage.sync_run_id == run_id)
            .order_by(ProviderReportPage.page_index)
            .limit(per_endpoint)
        )
        pages.extend(
            StoredPage(
                endpoint=endpoint,
                page_index=row.page_index,
                request_params=row.request_params,
                payload=row.payload,
            )
            for row in rows
        )
    return pages


def write_capture(
    pages: Iterable[StoredPage], out_dir: Path, provider: str, redactor: Redactor
) -> list[Path]:
    """Redacted payload files plus `index.json` under `out_dir/provider`, which must be absent
    or empty so a capture never overwrites a file."""
    target = out_dir / provider
    if target.exists() and any(target.iterdir()):
        raise OperationError(f"{target} is not empty; name a new output directory")
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index: list[dict[str, Any]] = []
    ordinals: dict[str, int] = {}
    for page in pages:
        ordinals[page.endpoint] = ordinals.get(page.endpoint, 0) + 1
        path = target / f"{page.endpoint}_page{ordinals[page.endpoint]}.json"
        path.write_text(_json(redactor.redact(page.payload)))
        written.append(path)
        index.append(
            {
                "file": path.name,
                "endpoint": page.endpoint,
                "page_index": page.page_index,
                "request_params": redactor.redact(page.request_params),
            }
        )
    index_path = target / "index.json"
    index_path.write_text(_json({"provider": provider, "pages": index}))
    written.append(index_path)
    return written


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.capture_fixtures", description=__doc__)
    parser.add_argument("provider", choices=provider_names())
    parser.add_argument("out_dir", type=Path, help="local directory the files are written to")
    parser.add_argument("--org", default="default", help="organization slug (default: default)")
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_PAGES,
        help=f"pages per endpoint, from the newest run (default {DEFAULT_PAGES})",
    )
    args = parser.parse_args(argv)
    if args.pages < 1:
        parser.error("--pages must be 1 or more")

    def operation() -> int:
        with SessionLocal() as session:
            try:
                org = get_org(session, args.org)
            except UnknownOrganization as exc:
                raise OperationError(f"no organization {args.org!r}") from exc
            pages = newest_pages(session, org.id, args.provider, per_endpoint=args.pages)
        if not pages:
            raise OperationError(
                f"no stored {args.provider} pages in organization {args.org!r}; connect the "
                "account and let a sync run first (raw pages past retention are purged)"
            )
        redactor = Redactor()
        written = write_capture(pages, args.out_dir, args.provider, redactor)
        print(f"wrote {len(written)} files to {args.out_dir / args.provider}")
        print(redactor.summary())
        print(REVIEW_REMINDER)
        return 0

    return run(operation)


if __name__ == "__main__":
    raise SystemExit(main())
