"""The organization's signal webhook: where it posts and what it sent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WebhookDeliveryOut(BaseModel):
    # The row id; `POST /orgs/{org}/webhook/deliveries/{id}/resend` posts it again.
    id: int
    kind: str
    provider: str
    reference: str
    status: Literal["pending", "sent", "failed", "skipped"]
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
    next_attempt_at: datetime


class WebhookOut(BaseModel):
    # False when the operator lists no host in COSTURA_WEBHOOK_HOSTS: nothing can be saved.
    egress_enabled: bool
    allowed_hosts: list[str]
    configured: bool
    # The host of the saved URL; the path is the credential and is never returned.
    host: str | None
    created_at: datetime | None
    # True when the saved host was later dropped from COSTURA_WEBHOOK_HOSTS.
    host_blocked: bool
    # "off", "weekly" (Mondays) or "monthly" (the 2nd): the summary posted on a schedule.
    digest: Literal["off", "weekly", "monthly"] = "off"
    deliveries: list[WebhookDeliveryOut]


class WebhookSavedOut(WebhookOut):
    # Returned once, on save: receivers verify `X-Costura-Signature` with it.
    signing_secret: str


class WebhookIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class WebhookTestOut(BaseModel):
    delivered: bool
    error: str | None


class WebhookDigestIn(BaseModel):
    digest: Literal["off", "weekly", "monthly"]
