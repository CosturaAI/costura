"""Facts members record by hand: who answers for a key or a workspace, which key is one
person's own, and the checks a budget scope must pass before it is stored."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import accounts
from costura.errors import DomainError, InvalidInput, NotFound
from costura.models import (
    OwnerAssignment,
    PersonalKeyAssignment,
    ProviderApiKey,
    ProviderUser,
    ProviderWorkspace,
    Team,
    User,
)
from costura.models.budget import PERSON_BUDGET_PROVIDER, BudgetScopeKind
from costura.models.owner import OwnerAssignmentKind
from costura.providers.records import USER_KIND_USER
from costura.providers.registry import provider_names
from costura.spend.inventory import InventoryResolver
from costura.spend.scope import provider_clause


class BudgetNeedsProvider(DomainError):
    """An organization or workspace budget asked for under `all`. Answers 400."""

    status = 400
    code = "budget_needs_provider"


@dataclass(frozen=True)
class OwnerAssignmentView:
    row: OwnerAssignment
    assigned_by: str | None


@dataclass(frozen=True)
class PersonalKeyView:
    row: PersonalKeyAssignment
    assigned_by: str | None


def _email_of(session: Session, user_id: int | None) -> str | None:
    user = None if user_id is None else session.get(User, user_id)
    return None if user is None else user.email


def owner_assignments(session: Session, org_id: int, provider: str) -> list[OwnerAssignmentView]:
    rows = session.scalars(
        select(OwnerAssignment)
        .where(OwnerAssignment.organization_id == org_id, OwnerAssignment.provider == provider)
        .order_by(OwnerAssignment.kind, OwnerAssignment.external_id)
    ).all()
    return [OwnerAssignmentView(row, _email_of(session, row.assigned_by)) for row in rows]


def _account_of_entity(
    session: Session, org_id: int, provider: str, kind: OwnerAssignmentKind, external_id: str
) -> int:
    """The provider account a key or workspace belongs to, from the inventory; the provider's
    default account when the inventory does not know the id (an assignment made ahead of the
    first sync)."""
    table = ProviderApiKey if kind == "api_key" else ProviderWorkspace
    account_id = session.scalar(
        select(table.provider_account_id)
        .where(
            table.organization_id == org_id,
            table.provider == provider,
            table.external_id == external_id,
        )
        .order_by(table.missing_since.is_not(None), table.id.desc())
        .limit(1)
    )
    if account_id is not None:
        return int(account_id)
    account = accounts.ensure_default_account(session, org_id, provider)
    session.flush()
    return account.id


def set_owner_assignment(
    session: Session,
    org_id: int,
    provider: str,
    kind: OwnerAssignmentKind,
    external_id: str,
    *,
    email: str,
    note: str | None,
    user_id: int,
) -> OwnerAssignmentView:
    account_id = _account_of_entity(session, org_id, provider, kind, external_id)
    row = session.get(OwnerAssignment, (org_id, provider, account_id, kind, external_id))
    if row is None:
        row = OwnerAssignment(
            organization_id=org_id,
            provider=provider,
            provider_account_id=account_id,
            kind=kind,
            external_id=external_id,
        )
        session.add(row)
    row.email = email
    row.note = (note or "").strip() or None
    row.assigned_by = user_id
    session.flush()
    session.refresh(row)
    return OwnerAssignmentView(row, _email_of(session, user_id))


def delete_owner_assignment(
    session: Session, org_id: int, provider: str, kind: OwnerAssignmentKind, external_id: str
) -> None:
    account_id = _account_of_entity(session, org_id, provider, kind, external_id)
    row = session.get(OwnerAssignment, (org_id, provider, account_id, kind, external_id))
    if row is None:
        raise NotFound("no contact assigned")
    session.delete(row)
    session.flush()


def personal_keys(session: Session, org_id: int, provider: str) -> list[PersonalKeyView]:
    rows = session.scalars(
        select(PersonalKeyAssignment)
        .where(
            PersonalKeyAssignment.organization_id == org_id,
            provider_clause(PersonalKeyAssignment.provider, provider),
        )
        .order_by(PersonalKeyAssignment.provider, PersonalKeyAssignment.api_key_id)
    ).all()
    return [PersonalKeyView(row, _email_of(session, row.assigned_by)) for row in rows]


def person_exists(session: Session, org_id: int, email: str) -> bool:
    """True when a user (not a service account) of the organization's inventory, on any
    provider, uses this e-mail."""
    count = session.scalar(
        select(func.count())
        .select_from(ProviderUser)
        .where(
            ProviderUser.organization_id == org_id,
            ProviderUser.kind == USER_KIND_USER,
            func.lower(ProviderUser.email) == email.strip().lower(),
        )
    )
    return (count or 0) > 0


def set_personal_key(
    session: Session,
    org_id: int,
    provider: str,
    api_key_id: str,
    *,
    email: str,
    user_id: int,
    resolver: InventoryResolver,
) -> PersonalKeyView:
    """422 when no user of the inventory uses the e-mail, 404 when the key is unknown."""
    if not person_exists(session, org_id, email):
        raise InvalidInput("no provider account in this organization uses that e-mail")
    if resolver.api_key(provider, api_key_id) is None:
        raise NotFound("api key not found")
    row = session.get(PersonalKeyAssignment, (org_id, provider, api_key_id))
    if row is None:
        row = PersonalKeyAssignment(
            organization_id=org_id, provider=provider, api_key_id=api_key_id
        )
        session.add(row)
    row.email = email
    row.assigned_by = user_id
    session.flush()
    session.refresh(row)
    return PersonalKeyView(row, _email_of(session, user_id))


def delete_personal_key(session: Session, org_id: int, provider: str, api_key_id: str) -> None:
    row = session.get(PersonalKeyAssignment, (org_id, provider, api_key_id))
    if row is None:
        raise NotFound("key is not marked personal")
    session.delete(row)
    session.flush()


def workspace_exists(session: Session, org_id: int, provider: str, external_id: str) -> bool:
    count = session.scalar(
        select(func.count())
        .select_from(ProviderWorkspace)
        .where(
            ProviderWorkspace.organization_id == org_id,
            ProviderWorkspace.provider == provider,
            ProviderWorkspace.external_id == external_id,
        )
    )
    return (count or 0) > 0


def require_budget_provider(provider: str, scope_kind: BudgetScopeKind) -> None:
    """A person budget spans every provider; an organization budget belongs to one provider
    or, under `all`, to every provider together; a workspace belongs to one."""
    if scope_kind in ("person", "team") and provider != PERSON_BUDGET_PROVIDER:
        raise InvalidInput(f"a {scope_kind} budget is set under provider all, not one provider")
    if scope_kind == "workspace" and provider == PERSON_BUDGET_PROVIDER:
        raise BudgetNeedsProvider(
            f"choose a provider: this budget needs one of {list(provider_names())}"
        )


def check_budget_scope(
    session: Session, org_id: int, provider: str, scope_kind: BudgetScopeKind, scope_id: str
) -> None:
    """The scope a budget is about to be stored for exists: 404 for an unknown workspace or
    person."""
    require_budget_provider(provider, scope_kind)
    if scope_kind == "workspace" and not workspace_exists(session, org_id, provider, scope_id):
        raise NotFound("workspace not found")
    if scope_kind == "person" and not person_exists(session, org_id, scope_id):
        raise NotFound("person not found")
    if scope_kind == "team" and not session.scalar(
        select(func.count())
        .select_from(Team)
        .where(Team.organization_id == org_id, Team.slug == scope_id)
    ):
        raise NotFound("team not found")
