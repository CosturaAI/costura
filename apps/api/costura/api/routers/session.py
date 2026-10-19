"""Sign-in, sign-out and `/me`: the routes outside the organization scope that manage a session."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response

from costura import (
    audit,
    auth,
    google_oidc,
    identity_policy,
    members,
)
from costura.api import schemas
from costura.api.deps import (
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    bearer_token,
)
from costura.api.guard import (
    LOCAL_WRITE_ENVIRONMENTS,
    operator_credentials_match,
    operator_sign_in_enabled,
    require_local_write,
)
from costura.api.presenters.common import organization_out
from costura.models import User
from costura.orgs import (
    demo_org_slug,
    visible_orgs,
)

router = APIRouter()
google_client_factory = google_oidc.GoogleOidcClient


@router.post("/auth/dev-sign-in", response_model=schemas.SignInOut, status_code=201)
def dev_sign_in(
    request: Request, session: SessionDep, settings: SettingsDep, body: schemas.DevSignInIn
) -> schemas.SignInOut:
    """Development stand-in for Google sign-in: any e-mail opens a session, creating the user
    on first sight. 403 in production and outside loopback, unless the body is the configured
    operator e-mail and secret. 422 on an e-mail without `@`."""
    if operator_credentials_match(body.email, body.secret, settings):
        signed = auth.sign_in_dev(session, body.email, body.name)
        audit.record("sign_in", method="operator", user_id=signed.user.id)
        return schemas.SignInOut(
            token=signed.token, expires_at=signed.expires_at, user=_current_user(signed.user)
        )
    if settings.costura_env not in LOCAL_WRITE_ENVIRONMENTS:
        if settings.operator_available:
            audit.record("sign_in_failed", method="operator")
        raise HTTPException(status_code=403, detail="dev sign-in is disabled in this environment")
    require_local_write(request)
    signed = auth.sign_in_dev(session, body.email, body.name)
    return schemas.SignInOut(
        token=signed.token, expires_at=signed.expires_at, user=_current_user(signed.user)
    )


@router.get("/auth/google", response_model=schemas.GoogleAuthStatusOut)
def google_status(settings: SettingsDep) -> schemas.GoogleAuthStatusOut:
    """Public capability state; no credential value is returned."""
    return schemas.GoogleAuthStatusOut(
        enabled=settings.google_available,
        dev_sign_in_enabled=settings.costura_env in LOCAL_WRITE_ENVIRONMENTS,
        operator_sign_in_enabled=operator_sign_in_enabled(settings),
    )


@router.post(
    "/auth/google/authorization",
    response_model=schemas.GoogleAuthorizationOut,
    status_code=201,
)
def google_authorization(
    session: SessionDep, settings: SettingsDep
) -> schemas.GoogleAuthorizationOut:
    """Create a short-lived, one-use state and PKCE authorization request."""
    try:
        started = google_oidc.begin(session, settings)
    except google_oidc.GoogleOidcError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return schemas.GoogleAuthorizationOut(
        authorization_url=started.url,
        state=started.state,
        nonce=started.nonce,
        code_verifier=started.code_verifier,
        expires_at=started.expires_at,
    )


@router.post("/auth/google/callback", response_model=schemas.SignInOut, status_code=201)
def google_callback(
    session: SessionDep, settings: SettingsDep, body: schemas.GoogleCallbackIn
) -> schemas.SignInOut:
    """Consume the browser-bound state, exchange the code, verify the ID token, then sign in."""
    try:
        google_oidc.consume(session, body.state, body.nonce, body.code_verifier)
        identity = google_client_factory().complete(
            settings,
            code=body.code,
            nonce=body.nonce,
            code_verifier=body.code_verifier,
        )
        signed = auth.sign_in_google(session, identity.email, identity.name)
    except google_oidc.GoogleOidcError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except identity_policy.SignupClosed as exc:
        audit.record("sign_in_failed", method="google")
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    audit.record("sign_in", method="google", user_id=signed.user.id)
    return schemas.SignInOut(
        token=signed.token, expires_at=signed.expires_at, user=_current_user(signed.user)
    )


@router.post("/auth/sign-out", status_code=204)
def sign_out(request: Request, session: SessionDep, _user: CurrentUserDep) -> Response:
    """Delete the session behind the bearer token; the token stops resolving at once."""
    token = bearer_token(request)
    if token is not None:
        auth.sign_out(session, token)
    audit.record("sign_out", user_id=_user.id)
    return Response(status_code=204)


@router.delete("/auth/sessions", status_code=204)
def sign_out_everywhere(session: SessionDep, user: CurrentUserDep) -> Response:
    """Delete every session of the signed-in user, this one included: the answer to a leaked
    or forgotten token."""
    auth.sign_out_everywhere(session, user)
    audit.record("sign_out_everywhere", user_id=user.id)
    return Response(status_code=204)


@router.get("/me", response_model=schemas.MeOut)
def me(session: SessionDep, user: CurrentUserDep) -> schemas.MeOut:
    """The signed-in user, the organizations they belong to, the slug of the public sample
    organization when seeded (it is not among `organizations`), and the invitations waiting
    for this e-mail."""
    return schemas.MeOut(
        user=_current_user(user),
        organizations=[organization_out(o, role) for o, role in visible_orgs(session, user.id)],
        demo_org=demo_org_slug(session),
        invitations=[
            schemas.PendingInvitationOut(
                id=invitation.id,
                organization=organization_out(org, None),
                role=cast(schemas.Role, invitation.role),
                invited_by=None if sender is None else sender.email,
                expires_at=invitation.expires_at,
            )
            for invitation, org, sender in members.invitations_for(session, user)
        ],
    )


def _current_user(user: User) -> schemas.CurrentUserOut:
    return schemas.CurrentUserOut(email=user.email, name=user.name)
