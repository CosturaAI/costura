"""Routes under `/api/v1`. Every route under `/orgs/{org}` reads through `OrgDep` (a signed-in
member, or anyone at all on the public demo organization, session or not) and writes through
`VerifiedWriteDep` (`costura.api.guard`) plus one of three organization dependencies:
`WritableOrgDep` (403 on the demo organization; the personal writes and leaving stop here),
`OperatorOrgDep` (owner or member: imports, anomaly triage, owner assignments, the
getting-started card) and `OwnedOrgDep` (owner: keys, budgets, reset, members and
invitations). `tests/test_api_access.py` pins which route uses which. `/auth/*`, `/me`, `POST /orgs`
and `/invitations/*` sit outside the organization scope.

Syncs never run inside a request: the connection PUT and the sync POST insert a `queued`
`scheduler_runs` row and answer with its id. `costura.ops.worker` claims and executes the
row; the browser polls `GET /orgs/{org}/setup` through running to terminal status.

Each slice lives in `costura.api.routers`; this module only composes them into one router.
"""

from fastapi import APIRouter

from costura.api.routers import (
    anomalies,
    audit,
    budgets,
    connections,
    connections_prices,
    connections_sync,
    copilot,
    inventory,
    invoices,
    organizations,
    session,
    setup,
    signals,
    spend,
    teams,
    webhooks,
)

# FastAPI keeps an included router nested, so `router.routes` lists these, not their routes.
DOMAIN_ROUTERS: tuple[APIRouter, ...] = tuple(
    module.router
    for module in (
        session,
        organizations,
        spend,
        inventory,
        anomalies,
        audit,
        signals,
        connections,
        connections_prices,
        connections_sync,
        setup,
        budgets,
        invoices,
        copilot,
        teams,
        webhooks,
    )
)

router = APIRouter()
for domain_router in DOMAIN_ROUTERS:
    router.include_router(domain_router)
