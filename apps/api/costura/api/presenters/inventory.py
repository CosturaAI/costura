"""Response shapes for the inventory pages."""

from typing import Literal

from costura.api import schemas
from costura.models import ProviderApiKey, ProviderUser, ProviderWorkspace
from costura.spend.inventory import InventoryResolver, InventorySearchHit
from costura.spend.posture import PostureReader


def search_out(hits: list[InventorySearchHit]) -> schemas.InventorySearchOut:
    return schemas.InventorySearchOut(
        items=[
            schemas.InventorySearchItem(
                kind=hit.kind,
                id=hit.id,
                label=hit.label,
                providers=list(hit.providers),
                provider_account_id=hit.provider_account_id,
                provider_account_label=hit.provider_account_label,
                hint=hit.hint,
            )
            for hit in hits
        ]
    )


def api_key_out(
    resolver: InventoryResolver, k: ProviderApiKey, posture: PostureReader
) -> schemas.ApiKeyOut:
    facts = posture.of(k)
    return schemas.ApiKeyOut(
        provider=k.provider,
        provider_account_id=k.provider_account_id,
        provider_account_label=resolver.provider_account_label(k.provider_account_id),
        external_id=k.external_id,
        name=k.name,
        partial_key_hint=k.partial_key_hint,
        workspace_external_id=k.workspace_external_id,
        workspace=resolver.workspace_label(k.provider, k.workspace_external_id),
        created_by_external_id=k.created_by_external_id,
        created_by=resolver.user_email(k.provider, k.created_by_external_id),
        status=k.status,
        created_at=k.created_at,
        expires_at=k.expires_at,
        last_seen_at=k.last_seen_at,
        missing_since=k.missing_since,
        missing=k.missing_since is not None,
        person=resolver.key_person(k.provider, k.external_id),
        person_source=_person_source(resolver, k),
        last_used_at=facts.last_used_at,
        last_used_source=facts.last_used_source,
        principal_type=k.principal_type,
        scope_type=k.scope_type,
        limit_reported=k.limit_reported,
        spend_limit=schemas.money(k.spend_limit),
        limit_remaining=schemas.money(k.limit_remaining),
        limit_reset=k.limit_reset,
        owner=facts.owner,
        owner_source=facts.owner_source,
        creator_left=facts.creator_left,
    )


def _person_source(
    resolver: InventoryResolver, k: ProviderApiKey
) -> Literal["marked", "claude_code"] | None:
    if resolver.marked_person(k.provider, k.external_id) is not None:
        return "marked"
    if resolver.key_person(k.provider, k.external_id) is not None:
        return "claude_code"
    return None


def workspace_out(
    resolver: InventoryResolver,
    w: ProviderWorkspace,
    key_counts: dict[tuple[str, str | None], int],
) -> schemas.WorkspaceOut:
    return schemas.WorkspaceOut(
        provider=w.provider,
        provider_account_id=w.provider_account_id,
        provider_account_label=resolver.provider_account_label(w.provider_account_id),
        external_id=w.external_id,
        name=w.name,
        archived_at=w.archived_at,
        admins=resolver.workspace_admins(w.provider, w.external_id),
        api_keys=key_counts.get((w.provider, w.external_id), 0),
        created_at=w.created_at,
        last_seen_at=w.last_seen_at,
        missing_since=w.missing_since,
        missing=w.missing_since is not None,
    )


def user_out(u: ProviderUser) -> schemas.UserOut:
    return schemas.UserOut(
        provider=u.provider,
        external_id=u.external_id,
        email=u.email,
        role=u.role,
        kind=u.kind,
        added_at=u.added_at,
        last_seen_at=u.last_seen_at,
        missing_since=u.missing_since,
        missing=u.missing_since is not None,
        last_active_at=u.last_active_at,
        pending_removal_at=u.pending_removal_at,
        limit_reported=u.limit_reported,
        spend_limit=schemas.money(u.spend_limit),
    )
