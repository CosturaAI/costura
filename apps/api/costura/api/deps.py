"""Request-scoped dependencies: database session, signed-in user, organization, provider,
month window."""

import re
from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Query, Request
from sqlalchemy.orm import Session

from costura import audit, auth
from costura.config import Settings, get_settings
from costura.db import SessionLocal
from costura.models import User
from costura.models.organization import Organization
from costura.models.user import OPERATOR_ROLES
from costura.orgs import UnknownOrganization, get_org
from costura.providers.registry import ALL, provider_names
from costura.spend.membership import membership
from costura.spend.query_contract import MAX_RANGE_DAYS
from costura.spend.window import Window

MONTH_PATTERN = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])$")
FIRST_DAY = date(2000, 1, 1)
LAST_DAY = date(2099, 12, 31)
UNAUTHENTICATED = "sign in first: send the Costura session as `Authorization: Bearer <token>`"
DEMO_READ_ONLY = "demo organization is read-only"
OWNER_ONLY = "this action needs the owner role in the organization"
MEMBER_ONLY = "this action needs the member or owner role in the organization; you are a viewer"


def get_session() -> Iterator[Session]:
    """One unit of work per request: commit when the route returns, roll back when it raises.
    Function scope runs the commit before the response is sent, so a failed commit answers
    500 instead of a success the database never recorded."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def request_settings(request: Request) -> Settings:
    """The settings a route would receive through `SettingsDep`, for code that holds the
    request but is not a route (middleware, guards): an app override of `get_settings` applies
    here too."""
    app = request.scope.get("app")
    factory = app.dependency_overrides.get(get_settings, get_settings) if app else get_settings
    return factory()


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_optional_user(request: Request, session: SessionDep) -> User | None:
    """The signed-in user, or None without a bearer token or with one that is unknown or
    expired. Routes that serve the public sample organization read through this one."""
    token = bearer_token(request)
    user = None if token is None else auth.resolve_session(session, token)
    if user is not None:
        audit.remember_actor(user.id, user.email)
    return user


OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]


def get_current_user(user: OptionalUserDep) -> User:
    """401 without a bearer token, or with one that is unknown or expired."""
    if user is None:
        raise HTTPException(
            status_code=401, detail=UNAUTHENTICATED, headers={"WWW-Authenticate": "Bearer"}
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_organization(
    session: SessionDep, user: OptionalUserDep, org: Annotated[str, Path()]
) -> Organization:
    """The organization named in the path. The demo organization is public: anyone, signed
    in or not, reads it. Every other organization needs a session (401) and a membership;
    an unknown slug and an organization the user cannot see answer the same 404."""
    found = get_org(session, org)
    if found.is_demo:
        return found
    if user is None:
        raise HTTPException(
            status_code=401, detail=UNAUTHENTICATED, headers={"WWW-Authenticate": "Bearer"}
        )
    if membership(session, found.id, user.id) is None:
        raise HTTPException(status_code=404, detail=str(UnknownOrganization(org)))
    return found


OrgDep = Annotated[Organization, Depends(get_organization)]


def get_writable_organization(org: OrgDep) -> Organization:
    """Every write route scoped to an organization goes through here (directly or through
    `OperatorOrgDep` and `OwnedOrgDep`): the demo organization answers 403. Creating an
    organization, the invitation routes and `/auth/*` are not scoped to one and do not. On
    its own it allows any role, so only the personal writes (the alerts opt-in and the read
    markers) stop here."""
    if org.is_demo:
        raise HTTPException(status_code=403, detail=DEMO_READ_ONLY)
    return org


WritableOrgDep = Annotated[Organization, Depends(get_writable_organization)]


def get_operating_organization(
    session: SessionDep, user: CurrentUserDep, org: WritableOrgDep
) -> Organization:
    """The writes that change what the organization holds (imports, anomaly triage, owner
    assignments, personal keys, the getting-started card) need `owner` or `member`; a
    `viewer` answers 403."""
    member = membership(session, org.id, user.id)
    if member is None or member.role not in OPERATOR_ROLES:
        raise HTTPException(status_code=403, detail=MEMBER_ONLY)
    return org


OperatorOrgDep = Annotated[Organization, Depends(get_operating_organization)]


def get_owned_organization(
    session: SessionDep, user: CurrentUserDep, org: WritableOrgDep
) -> Organization:
    """The writes that replace the provider key, wipe the organization or move money
    thresholds need the `owner` role; a `member` answers 403."""
    member = membership(session, org.id, user.id)
    if member is None or member.role != "owner":
        raise HTTPException(status_code=403, detail=OWNER_ONLY)
    return org


OwnedOrgDep = Annotated[Organization, Depends(get_owned_organization)]


def get_provider(provider: Annotated[str, Path()]) -> str:
    """A registered provider name, or the `all` scope for aggregated reads."""
    if provider != ALL and provider not in provider_names():
        raise HTTPException(status_code=404, detail=f"unknown provider {provider!r}")
    return provider


ProviderDep = Annotated[str, Depends(get_provider)]


def get_concrete_provider(provider: ProviderDep) -> str:
    """Routes that talk to one provider (sync, reconcile, connection, budgets) refuse `all`."""
    if provider == ALL:
        raise HTTPException(
            status_code=400,
            detail=f"choose a provider: this route needs one of {list(provider_names())}",
        )
    return provider


ConcreteProviderDep = Annotated[str, Depends(get_concrete_provider)]


def get_window(month: Annotated[str, Path()]) -> Window:
    if not MONTH_PATTERN.match(month):
        raise HTTPException(
            status_code=422, detail=f"month must be YYYY-MM between 2000 and 2099, got {month!r}"
        )
    return Window.for_month(month)


WindowDep = Annotated[Window, Depends(get_window)]

DEMO_MAX_RANGE_DAYS = 400


def check_date_range(start: date, end: date, *, longest: int = MAX_RANGE_DAYS) -> None:
    """422 unless `start..end` is ordered, inside 2000-2099 and at most `longest` days."""
    if start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    if start < FIRST_DAY or end > LAST_DAY:
        raise HTTPException(status_code=422, detail="dates must fall between 2000 and 2099")
    if (end - start).days + 1 > longest:
        raise HTTPException(status_code=422, detail=f"a range spans at most {longest} days")


def range_cap(org: Organization) -> int:
    """Longest range one request may ask for: `DEMO_MAX_RANGE_DAYS` on the public sample, which
    holds thirteen months and answers without a session, `MAX_RANGE_DAYS` elsewhere."""
    return DEMO_MAX_RANGE_DAYS if org.is_demo else MAX_RANGE_DAYS


def get_range_window(
    org: OrgDep,
    month: Annotated[str, Path()],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> Window:
    """The month, or `start..end` when both are given, capped by `range_cap`."""
    window = get_window(month)
    if start is None and end is None:
        return window
    if start is None or end is None:
        raise HTTPException(status_code=422, detail="start and end go together")
    check_date_range(start, end, longest=range_cap(org))
    return Window.for_dates(start, end)


RangeWindowDep = Annotated[Window, Depends(get_range_window)]
