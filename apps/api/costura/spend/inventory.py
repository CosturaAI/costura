"""Resolve provider ids found in spend rows to inventory names and people.

Loads the provider's snapshot once per resolver; ids absent from the inventory keep their raw
form with a `(not in inventory)` marker so the report never hides an unknown key. Every
internal lookup uses `(provider, external_id)`, including under the `all` scope where two
providers may issue the same id.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from costura.models import (
    PersonalKeyAssignment,
    ProviderAccount,
    ProviderApiKey,
    ProviderUser,
    ProviderWorkspace,
    ProviderWorkspaceMember,
    Team,
    TeamMember,
)
from costura.providers.records import USER_KIND_SERVICE_ACCOUNT, USER_KIND_USER
from costura.providers.registry import find_spec
from costura.spend.scope import provider_clause

DEFAULT_WORKSPACE_LABEL = "(default workspace)"
PLAYGROUND_LABEL = "(playground, no api key)"
DIRECT_USER_LABEL = "(direct user usage, no API key)"
API_KEY_REQUEST_LABEL = "(api key request)"
UNKNOWN_CREATOR_LABEL = "(unknown creator)"
NOT_IN_INVENTORY = "(not in inventory)"
WORKSPACE_ADMIN_ROLE = "workspace_admin"
CLAUDE_CODE_WORKSPACE_NAME = "Claude Code"
CLAUDE_CODE_KEY_PREFIX = "claude_code_key_"


@dataclass(frozen=True)
class ApiKeyInfo:
    provider: str
    external_id: str
    name: str
    partial_key_hint: str | None
    workspace_external_id: str | None
    created_by_external_id: str | None
    status: str
    missing: bool


@dataclass(frozen=True)
class WorkspaceInfo:
    provider: str
    external_id: str
    name: str
    archived: bool
    missing: bool


class InventoryResolver:
    def __init__(self, session: Session, org_id: int, provider: str) -> None:
        self.org_id = org_id
        self.provider = provider
        # Every provider account of the organization, so a row can be badged with the console
        # it was synced from. Loaded for every provider: badges cross the scope.
        self._accounts: dict[int, ProviderAccount] = {
            a.id: a
            for a in session.scalars(
                select(ProviderAccount).where(ProviderAccount.organization_id == org_id)
            )
        }
        self._load_inventory(session, org_id, provider)
        self._session = session
        self._teams_loaded = False

    def _load_teams(self) -> None:
        """Every team mapping of the organization, read on the first team lookup so a read
        that never groups by team pays nothing; teams cross providers, so the scope does not
        narrow them."""
        if self._teams_loaded:
            return
        self._teams_loaded = True
        session, org_id = self._session, self.org_id
        self._team_names = {
            t.slug: t.name
            for t in session.scalars(select(Team).where(Team.organization_id == org_id))
        }
        self._team_members: dict[tuple[str, str, str], str] = {
            (kind, provider, external_id): slug
            for kind, provider, external_id, slug in session.execute(
                select(TeamMember.kind, TeamMember.provider, TeamMember.external_id, Team.slug)
                .join(Team, Team.id == TeamMember.team_id)
                .where(TeamMember.organization_id == org_id)
            )
        }

    def team_of(
        self,
        provider: str,
        api_key_id: str | None,
        person: str | None,
        workspace_id: str | None,
    ) -> str | None:
        """The team a line counts under: its key's, else its person's, else its workspace's."""
        self._load_teams()
        if not self._team_members:
            return None
        for kind, scope, external_id in (
            ("api_key", provider, api_key_id),
            ("person", "all", person),
            ("workspace", provider, workspace_id),
        ):
            if external_id is None:
                continue
            team = self._team_members.get((kind, scope, external_id))
            if team is not None:
                return team
        return None

    def team_label(self, slug: str) -> str:
        self._load_teams()
        return self._team_names.get(slug, slug)

    def _load_inventory(self, session: Session, org_id: int, provider: str) -> None:
        workspaces = session.scalars(
            select(ProviderWorkspace).where(
                ProviderWorkspace.organization_id == org_id,
                provider_clause(ProviderWorkspace.provider, provider),
            )
        ).all()
        self._workspaces = {
            (w.provider, w.external_id): WorkspaceInfo(
                provider=w.provider,
                external_id=w.external_id,
                name=w.name,
                archived=w.archived_at is not None,
                missing=w.missing_since is not None,
            )
            for w in workspaces
        }
        self._users: dict[tuple[str, str], str] = {}
        self._user_kinds: dict[tuple[str, str], str] = {}
        self._missing_users: set[tuple[str, str]] = set()
        # Lowercased address -> the (provider, external_id) identities carrying it; service
        # accounts have no address and never join a person.
        self._people: dict[str, list[tuple[str, str]]] = {}
        for u in session.scalars(
            select(ProviderUser)
            .where(
                ProviderUser.organization_id == org_id,
                provider_clause(ProviderUser.provider, provider),
            )
            .order_by(ProviderUser.provider, ProviderUser.external_id)
        ):
            identity = (u.provider, u.external_id)
            self._users[identity] = u.email
            self._user_kinds[identity] = u.kind
            if u.missing_since is not None:
                self._missing_users.add(identity)
            if u.kind == USER_KIND_USER and "@" in u.email:
                self._people.setdefault(u.email.strip().lower(), []).append(identity)
        keys = session.scalars(
            select(ProviderApiKey).where(
                ProviderApiKey.organization_id == org_id,
                provider_clause(ProviderApiKey.provider, provider),
            )
        ).all()
        self._keys = {
            (k.provider, k.external_id): ApiKeyInfo(
                provider=k.provider,
                external_id=k.external_id,
                name=k.name,
                partial_key_hint=k.partial_key_hint,
                workspace_external_id=k.workspace_external_id,
                created_by_external_id=k.created_by_external_id,
                status=k.status,
                missing=k.missing_since is not None,
            )
            for k in keys
        }
        # (provider, api_key_id) -> lowercased e-mail of the person a member marked the key for.
        self._marked: dict[tuple[str, str], str] = {
            (row.provider, row.api_key_id): row.email.strip().lower()
            for row in session.scalars(
                select(PersonalKeyAssignment).where(
                    PersonalKeyAssignment.organization_id == org_id,
                    provider_clause(PersonalKeyAssignment.provider, provider),
                )
            )
        }
        self._admins: dict[tuple[str, str], list[str]] = {}
        for member in session.scalars(
            select(ProviderWorkspaceMember).where(
                ProviderWorkspaceMember.organization_id == org_id,
                provider_clause(ProviderWorkspaceMember.provider, provider),
                ProviderWorkspaceMember.role == WORKSPACE_ADMIN_ROLE,
                ProviderWorkspaceMember.missing_since.is_(None),
            )
        ):
            self._admins.setdefault((member.provider, member.workspace_external_id), []).append(
                self.user_email(member.provider, member.user_external_id)
            )

    def provider_account(self, account_id: int | None) -> ProviderAccount | None:
        return None if account_id is None else self._accounts.get(account_id)

    def provider_account_label(self, account_id: int | None) -> str | None:
        """The label of one provider account ("Acme"); None for an unknown id."""
        account = self.provider_account(account_id)
        return None if account is None else account.label

    def workspace(self, provider: str, external_id: str | None) -> WorkspaceInfo | None:
        return None if external_id is None else self._workspaces.get((provider, external_id))

    def workspace_label(self, provider: str, external_id: str | None) -> str:
        if external_id is None:
            return DEFAULT_WORKSPACE_LABEL
        info = self._workspaces.get((provider, external_id))
        if info is None:
            return f"{external_id} {NOT_IN_INVENTORY}"
        suffix = " [archived]" if info.archived else ""
        return f"{info.name} ({external_id}){suffix}"

    def workspace_admins(self, provider: str, external_id: str | None) -> list[str]:
        if external_id is None:
            return []
        return sorted(self._admins.get((provider, external_id), []))

    def api_key(self, provider: str, external_id: str | None) -> ApiKeyInfo | None:
        return None if external_id is None else self._keys.get((provider, external_id))

    def api_key_label(self, provider: str, external_id: str | None) -> str:
        if external_id is None:
            return PLAYGROUND_LABEL
        info = self._keys.get((provider, external_id))
        if info is None:
            return f"{external_id} {NOT_IN_INVENTORY}"
        return f"{info.name} ({external_id})"

    def user_email(self, provider: str, external_id: str | None) -> str:
        if external_id is None:
            return ""
        return self._users.get((provider, external_id), f"{external_id} {NOT_IN_INVENTORY}")

    def user_left(self, provider: str, external_id: str | None) -> bool:
        return external_id is not None and (provider, external_id) in self._missing_users

    def user_kind(self, provider: str, external_id: str | None) -> str | None:
        """`user`, `service_account`, or None when the id is not in the inventory."""
        if external_id is None:
            return None
        return self._user_kinds.get((provider, external_id))

    def person_of(self, provider: str, account_id: str | None) -> str | None:
        """The e-mail identity of an account across providers; None for service accounts,
        ids outside the inventory and API-key requests without a user."""
        if account_id is None:
            return None
        identity = (provider, account_id)
        if self._user_kinds.get(identity) != USER_KIND_USER:
            return None
        email = self._users[identity].strip().lower()
        return email if email in self._people else None

    def person_identities(self, email: str) -> list[tuple[str, str]]:
        """Every `(provider, external_id)` of one person in this resolver's scope."""
        return list(self._people.get(email.strip().lower(), []))

    def creator_of(self, provider: str, api_key_id: str | None) -> str | None:
        """External id of the user who created the key; None when unknown."""
        info = self.api_key(provider, api_key_id)
        return None if info is None else info.created_by_external_id

    def is_personal_key(self, provider: str, api_key_id: str | None) -> bool:
        """Whether Anthropic created the key for one person's Claude Code session."""
        info = self.api_key(provider, api_key_id)
        spec = find_spec(provider)
        if spec is None or not spec.personal_session_keys or info is None:
            return False
        workspace = self.workspace(provider, info.workspace_external_id)
        return info.name.startswith(CLAUDE_CODE_KEY_PREFIX) or (
            workspace is not None and workspace.name == CLAUDE_CODE_WORKSPACE_NAME
        )

    def personal_key_owner(self, provider: str, api_key_id: str | None) -> str | None:
        """The person behind a Claude Code key; service keys have no personal owner."""
        if not self.is_personal_key(provider, api_key_id):
            return None
        return self.creator_of(provider, api_key_id)

    def marked_person(self, provider: str, api_key_id: str | None) -> str | None:
        """The e-mail a member marked the key for; None when nobody marked it."""
        if api_key_id is None:
            return None
        return self._marked.get((provider, api_key_id))

    def marked_keys_of(self, email: str) -> list[tuple[str, str]]:
        """Provider and key ids a member marked as this person's own."""
        address = email.strip().lower()
        return [identity for identity, marked in self._marked.items() if marked == address]

    def key_person(self, provider: str, api_key_id: str | None) -> str | None:
        """The e-mail whose spend a key carries: the member's mark first, then the Claude Code
        key's creator; None for a service key."""
        marked = self.marked_person(provider, api_key_id)
        if marked is not None:
            return marked
        return self.person_of(provider, self.personal_key_owner(provider, api_key_id))

    def personal_key_identities_of(self, creator_id: str) -> list[tuple[str, str]]:
        """Claude Code key identities whose inventory creator is the requested person."""
        return [
            identity
            for identity, info in self._keys.items()
            if info.created_by_external_id == creator_id
            and identity not in self._marked
            and self.is_personal_key(info.provider, info.external_id)
        ]

    def api_key_identities_created_by(self, creator_id: str | None) -> list[tuple[str, str]]:
        """Provider and key ids whose inventory creator matches the requested identity."""
        return [
            identity
            for identity, info in self._keys.items()
            if info.created_by_external_id == creator_id
        ]

    def account_label(self, provider: str, account_id: str | None) -> str:
        """Usage made with an OAuth account (Claude Code login) instead of an API key."""
        if account_id is None:
            return API_KEY_REQUEST_LABEL
        return self.user_email(provider, account_id)


SEARCH_LIMIT_DEFAULT = 5
SEARCH_LIMIT_MAX = 8


@dataclass(frozen=True)
class InventorySearchHit:
    kind: Literal["person", "service", "api_key", "workspace"]
    id: str
    label: str
    providers: tuple[str, ...]
    provider_account_id: int | None
    provider_account_label: str | None
    hint: str | None


def search_inventory(
    session: Session, org_id: int, provider: str, query: str, limit: int
) -> list[InventorySearchHit]:
    """Current resources whose name, e-mail, id or key hint contains `query`.

    Ranking is exact, then prefix, then substring, compared case-insensitively and
    literally (`%` and `_` are characters, not wildcards). People collapse to one row
    per e-mail. Each kind keeps at most `limit` rows. Missing rows stay out.
    """
    needle = query.strip().lower()
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    prefix = f"{escaped}%"
    contains = f"%{escaped}%"
    labels = _account_labels(session, org_id)
    hits = [
        *_people(session, org_id, provider, needle, prefix, contains, limit, labels),
        *_services(session, org_id, provider, needle, prefix, contains, limit, labels),
        *_keys(session, org_id, provider, needle, prefix, contains, limit, labels),
        *_workspaces(session, org_id, provider, needle, prefix, contains, limit, labels),
    ]
    return hits


def _account_labels(session: Session, org_id: int) -> dict[int, str]:
    return {
        account.id: account.label
        for account in session.scalars(
            select(ProviderAccount).where(ProviderAccount.organization_id == org_id)
        )
    }


def _rank(column: object, needle: str, prefix: str) -> object:
    lowered = func.lower(func.coalesce(column, ""))
    return case((lowered == needle, 0), (lowered.like(prefix, escape="\\"), 1), else_=2)


def _contains(
    column: ColumnElement[str] | InstrumentedAttribute[str] | InstrumentedAttribute[str | None],
    contains: str,
) -> ColumnElement[bool]:
    return func.lower(func.coalesce(column, "")).like(contains, escape="\\")


def _people(
    session: Session,
    org_id: int,
    provider: str,
    needle: str,
    prefix: str,
    contains: str,
    limit: int,
    labels: dict[int, str],
) -> list[InventorySearchHit]:
    email_key = func.lower(func.trim(ProviderUser.email))
    rank = _rank(func.trim(ProviderUser.email), needle, prefix)
    rows = session.execute(
        select(
            email_key.label("id"),
            func.min(ProviderUser.email).label("label"),
            func.array_agg(func.distinct(ProviderUser.provider)).label("providers"),
            func.count().label("identities"),
            func.min(ProviderUser.provider_account_id).label("account_id"),
            func.min(ProviderUser.role).label("role"),
            func.min(rank).label("rank"),
        )
        .where(
            ProviderUser.organization_id == org_id,
            provider_clause(ProviderUser.provider, provider),
            ProviderUser.missing_since.is_(None),
            ProviderUser.kind == USER_KIND_USER,
            ProviderUser.email.contains("@"),
            _contains(func.trim(ProviderUser.email), contains),
        )
        .group_by(email_key)
        .order_by(func.min(rank), func.min(ProviderUser.email))
        .limit(limit)
    ).all()
    hits: list[InventorySearchHit] = []
    for row in rows:
        providers = tuple(sorted({str(name) for name in row.providers}))
        single = int(row.identities) == 1
        account_id = int(row.account_id) if single else None
        hits.append(
            InventorySearchHit(
                kind="person",
                id=str(row.id),
                label=str(row.label),
                providers=providers,
                provider_account_id=account_id,
                provider_account_label=labels.get(account_id) if account_id is not None else None,
                hint=str(row.role) if single else None,
            )
        )
    return hits


def _services(
    session: Session,
    org_id: int,
    provider: str,
    needle: str,
    prefix: str,
    contains: str,
    limit: int,
    labels: dict[int, str],
) -> list[InventorySearchHit]:
    rank = func.least(
        _rank(ProviderUser.email, needle, prefix),
        _rank(ProviderUser.external_id, needle, prefix),
    )
    rows = session.execute(
        select(ProviderUser, rank.label("rank"))
        .where(
            ProviderUser.organization_id == org_id,
            provider_clause(ProviderUser.provider, provider),
            ProviderUser.missing_since.is_(None),
            ProviderUser.kind == USER_KIND_SERVICE_ACCOUNT,
            or_(
                _contains(ProviderUser.email, contains),
                _contains(ProviderUser.external_id, contains),
            ),
        )
        .order_by(rank, ProviderUser.email, ProviderUser.external_id)
        .limit(limit)
    ).all()
    return [
        InventorySearchHit(
            kind="service",
            id=user.external_id,
            label=user.email,
            providers=(user.provider,),
            provider_account_id=user.provider_account_id,
            provider_account_label=labels.get(user.provider_account_id),
            hint=user.role or None,
        )
        for user, _rank_value in rows
    ]


def _keys(
    session: Session,
    org_id: int,
    provider: str,
    needle: str,
    prefix: str,
    contains: str,
    limit: int,
    labels: dict[int, str],
) -> list[InventorySearchHit]:
    rank = func.least(
        _rank(ProviderApiKey.name, needle, prefix),
        _rank(ProviderApiKey.partial_key_hint, needle, prefix),
        _rank(ProviderApiKey.external_id, needle, prefix),
    )
    rows = session.scalars(
        select(ProviderApiKey)
        .where(
            ProviderApiKey.organization_id == org_id,
            provider_clause(ProviderApiKey.provider, provider),
            ProviderApiKey.missing_since.is_(None),
            or_(
                _contains(ProviderApiKey.name, contains),
                _contains(ProviderApiKey.partial_key_hint, contains),
                _contains(ProviderApiKey.external_id, contains),
            ),
        )
        .order_by(rank, ProviderApiKey.name, ProviderApiKey.external_id)
        .limit(limit)
    ).all()
    return [
        InventorySearchHit(
            kind="api_key",
            id=key.external_id,
            label=key.name,
            providers=(key.provider,),
            provider_account_id=key.provider_account_id,
            provider_account_label=labels.get(key.provider_account_id),
            hint=key.partial_key_hint,
        )
        for key in rows
    ]


def _workspaces(
    session: Session,
    org_id: int,
    provider: str,
    needle: str,
    prefix: str,
    contains: str,
    limit: int,
    labels: dict[int, str],
) -> list[InventorySearchHit]:
    rank = func.least(
        _rank(ProviderWorkspace.name, needle, prefix),
        _rank(ProviderWorkspace.external_id, needle, prefix),
    )
    rows = session.scalars(
        select(ProviderWorkspace)
        .where(
            ProviderWorkspace.organization_id == org_id,
            provider_clause(ProviderWorkspace.provider, provider),
            ProviderWorkspace.missing_since.is_(None),
            or_(
                _contains(ProviderWorkspace.name, contains),
                _contains(ProviderWorkspace.external_id, contains),
            ),
        )
        .order_by(rank, ProviderWorkspace.name, ProviderWorkspace.external_id)
        .limit(limit)
    ).all()
    return [
        InventorySearchHit(
            kind="workspace",
            id=workspace.external_id,
            label=workspace.name,
            providers=(workspace.provider,),
            provider_account_id=workspace.provider_account_id,
            provider_account_label=labels.get(workspace.provider_account_id),
            hint="archived" if workspace.archived_at is not None else None,
        )
        for workspace in rows
    ]
