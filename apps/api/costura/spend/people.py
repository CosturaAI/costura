"""One e-mail across the providers in scope: the inventory users carrying it and the live keys
each created."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from costura.errors import DomainError
from costura.models import ProviderApiKey, ProviderUser
from costura.providers.records import USER_KIND_USER
from costura.providers.registry import provider_names
from costura.spend.scope import provider_clause


class UnknownPerson(LookupError, DomainError):
    """No user in scope has the address."""

    status = 404
    code = "unknown_person"


@dataclass(frozen=True)
class PersonIdentity:
    provider: str
    external_id: str
    role: str
    added_at: datetime | None
    missing: bool
    keys_created: int


@dataclass(frozen=True)
class Person:
    email: str
    identities: list[PersonIdentity]
    providers: list[str]


def person(session: Session, org_id: int, provider: str, email: str) -> Person:
    """Raises `UnknownPerson` when no user of `provider` (or of any provider under `all`)
    carries the address."""
    address = email.strip().lower()
    users = list(
        session.scalars(
            select(ProviderUser)
            .where(
                ProviderUser.organization_id == org_id,
                provider_clause(ProviderUser.provider, provider),
                ProviderUser.kind == USER_KIND_USER,
                func.lower(ProviderUser.email) == address,
            )
            .order_by(ProviderUser.provider, ProviderUser.external_id)
        )
    )
    if not users:
        raise UnknownPerson("person not found")
    key_counts = {
        (line_provider, creator): int(count)
        for line_provider, creator, count in session.execute(
            select(ProviderApiKey.provider, ProviderApiKey.created_by_external_id, func.count())
            .where(
                ProviderApiKey.organization_id == org_id,
                provider_clause(ProviderApiKey.provider, provider),
                ProviderApiKey.missing_since.is_(None),
                tuple_(ProviderApiKey.provider, ProviderApiKey.created_by_external_id).in_(
                    [(u.provider, u.external_id) for u in users]
                ),
            )
            .group_by(ProviderApiKey.provider, ProviderApiKey.created_by_external_id)
        ).all()
    }
    seen = {u.provider for u in users}
    return Person(
        email=address,
        identities=[
            PersonIdentity(
                provider=u.provider,
                external_id=u.external_id,
                role=u.role,
                added_at=u.added_at,
                missing=u.missing_since is not None,
                keys_created=key_counts.get((u.provider, u.external_id), 0),
            )
            for u in users
        ],
        providers=[name for name in provider_names() if name in seen],
    )
