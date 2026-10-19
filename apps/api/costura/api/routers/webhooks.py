"""The organization's signal webhook: settings, a test message and the recent deliveries."""

from typing import cast

from fastapi import APIRouter
from sqlalchemy.orm import Session

from costura import audit, delivery
from costura.api import schemas
from costura.api.deps import OrgDep, OwnedOrgDep, SessionDep, SettingsDep
from costura.api.guard import VerifiedWriteDep
from costura.config import Settings
from costura.errors import InvalidInput
from costura.models.delivery import DigestCadence

router = APIRouter()


def _webhook_out(session: Session, settings: Settings, org_id: int) -> schemas.WebhookOut:
    row = delivery.destination(session, org_id)
    hosts = settings.webhook_hosts
    return schemas.WebhookOut(
        egress_enabled=bool(hosts),
        allowed_hosts=sorted(hosts),
        configured=row is not None,
        host=row.url_host if row else None,
        created_at=row.created_at if row else None,
        host_blocked=row is not None and row.url_host not in hosts,
        digest=cast(DigestCadence, row.digest) if row else "off",
        deliveries=[
            schemas.WebhookDeliveryOut(
                id=d.id,
                kind=d.kind,
                provider=d.provider,
                reference=d.reference,
                status=d.status,
                attempts=d.attempts,
                last_error=d.last_error,
                created_at=d.created_at,
                sent_at=d.sent_at,
                next_attempt_at=d.next_attempt_at,
            )
            for d in delivery.recent_deliveries(session, org_id)
        ],
    )


@router.get("/orgs/{org}/webhook", response_model=schemas.WebhookOut)
def get_webhook(session: SessionDep, org: OrgDep, settings: SettingsDep) -> schemas.WebhookOut:
    """Whether outbound delivery is on for this stack, the host of the saved URL and the 20
    newest deliveries (skipped ones left out)."""
    return _webhook_out(session, settings, org.id)


@router.put("/orgs/{org}/webhook", response_model=schemas.WebhookSavedOut)
def put_webhook(
    session: SessionDep,
    org: OwnedOrgDep,
    settings: SettingsDep,
    body: schemas.WebhookIn,
    _guard: VerifiedWriteDep,
) -> schemas.WebhookSavedOut:
    """Save the HTTPS URL a Slack-compatible webhook listens on, encrypted, with a new signing
    secret returned only here. The host must be in COSTURA_WEBHOOK_HOSTS (409 when that list
    is empty, 422 when the host is not on it). The first save marks the signals open now as
    skipped: only signals that appear afterwards are posted. Owner only."""
    saved = delivery.save_destination(session, settings, org.id, body.url)
    audit.record("webhook_saved", session=session, org_id=org.id, host=saved.destination.url_host)
    return schemas.WebhookSavedOut(
        **_webhook_out(session, settings, org.id).model_dump(),
        signing_secret=saved.signing_secret,
    )


@router.delete("/orgs/{org}/webhook", response_model=schemas.WebhookOut)
def delete_webhook(
    session: SessionDep, org: OwnedOrgDep, settings: SettingsDep, _guard: VerifiedWriteDep
) -> schemas.WebhookOut:
    """Remove the destination and its delivery history. Owner only."""
    delivery.remove_destination(session, org.id)
    audit.record("webhook_removed", session=session, org_id=org.id)
    return _webhook_out(session, settings, org.id)


@router.post("/orgs/{org}/webhook/test", response_model=schemas.WebhookTestOut)
def test_webhook(
    session: SessionDep, org: OwnedOrgDep, settings: SettingsDep, _guard: VerifiedWriteDep
) -> schemas.WebhookTestOut:
    """Post a test message to the saved URL now and report whether it answered 2xx. Owner
    only."""
    error = delivery.send_test(session, settings, org.id)
    return schemas.WebhookTestOut(delivered=error is None, error=error)


@router.post(
    "/orgs/{org}/webhook/deliveries/{delivery_id}/resend", response_model=schemas.WebhookTestOut
)
def resend_webhook_delivery(
    session: SessionDep,
    org: OwnedOrgDep,
    settings: SettingsDep,
    delivery_id: int,
    _guard: VerifiedWriteDep,
) -> schemas.WebhookTestOut:
    """Post one recorded delivery again, rendered from the signal as it stands now (payloads
    are not stored), and report whether the destination answered 2xx. The saved host must
    still be in COSTURA_WEBHOOK_HOSTS (409 otherwise); 404 for a delivery of another
    organization; 422 once the signal closed. A 2xx marks the row sent and puts failed rows
    back in the queue, as any successful post does. Owner only."""
    error = delivery.resend(session, settings, org.id, delivery_id)
    audit.record(
        "webhook_resent",
        session=session,
        org_id=org.id,
        target=str(delivery_id),
        delivered=error is None,
    )
    return schemas.WebhookTestOut(delivered=error is None, error=error)


@router.put("/orgs/{org}/webhook/digest", response_model=schemas.WebhookOut)
def put_webhook_digest(
    session: SessionDep,
    org: OwnedOrgDep,
    settings: SettingsDep,
    body: schemas.WebhookDigestIn,
    _guard: VerifiedWriteDep,
) -> schemas.WebhookOut:
    """Post a summary of the month, its projection and what needs a person to the webhook on
    Mondays (`weekly`) or on the 2nd (`monthly`), or stop (`off`). 422 without a saved
    webhook. Owner only."""
    row = delivery.destination(session, org.id)
    if row is None:
        raise InvalidInput("save a webhook URL first")
    row.digest = body.digest
    session.flush()
    audit.record("webhook_digest_set", session=session, org_id=org.id, digest=body.digest)
    return _webhook_out(session, settings, org.id)
