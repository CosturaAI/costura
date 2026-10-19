"""What the sample organization contains: a fictional company on four providers, written as
data so the tests can assert it without database ids.

Acme Analytics runs a support copilot, a search product and a research group. Anthropic
carries production and research traffic (API keys and Claude Code logins), OpenRouter fronts
a gateway with direct and BYOK traffic, OpenAI is split across two accounts, and every
engineer has a Cursor seat. The recurring stories repeat every `CYCLE_DAYS` from
`STORY_START`, so the latest episode is always recent; the dated events (a model switch, a
new key, a team that grows, a workspace that is archived) stay where they are.

Changing anything here that moves an amount is a new `DATASET_VERSION`.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from costura.demo.values import (
    cycle_day,
    growth,
    noise,
    ramp,
    weekday_factor,
)
from costura.providers.anthropic import PROVIDER as ANTHROPIC_ID
from costura.providers.cursor import PROVIDER as CURSOR_ID
from costura.providers.openai import PROVIDER as OPENAI_ID
from costura.providers.openrouter import PROVIDER as OPENROUTER_ID

DATASET_VERSION = 2
DEMO_NAME = "Acme Analytics (sample)"
# Twelve whole months before the current one, plus the current month to date.
MONTHS = 13
# The first cycle whose stories play; earlier months are quiet history.
STORY_START = date(2026, 6, 29)


@dataclass(frozen=True)
class Story:
    """A scripted change of one or more streams on given days of every cycle."""

    name: str
    kind: Literal["spike", "drop"]
    cycle_days: tuple[int, ...]
    factor: Decimal
    summary: str

    def factor_on(self, day: date) -> Decimal:
        if day >= STORY_START and cycle_day(day) in self.cycle_days:
            return self.factor
        return Decimal("1")


AGENT_RETRY_LOOP = Story(
    "agent-retry-loop",
    "spike",
    (9,),
    Decimal("5.5"),
    "prod-agent retries a failing tool call in a loop for one Wednesday",
)
CLAUDE_CODE_MIGRATION = Story(
    "claude-code-migration",
    "spike",
    (16,),
    Decimal("7"),
    "Carla runs a repository-wide migration with Claude Code on one Wednesday",
)
GATEWAY_OUTAGE = Story(
    "gateway-outage",
    "drop",
    (21, 22, 23, 24),
    Decimal("0.12"),
    "the OpenRouter gateway loses most of its traffic from Monday to Thursday",
)


@dataclass(frozen=True)
class Stream:
    """One principal's daily usage of one model: what a key, a login or a member spends."""

    principal: str
    workspace: str | None
    model: str
    # USD on a Monday at the growth reference, before the weekday, noise and stories.
    base: Decimal
    start: date | None = None
    end: date | None = None
    ramp_days: int = 0
    stories: tuple[Story, ...] = ()
    # Anthropic: usage of a member's own Claude Code login (no key, `account_id` set).
    login: bool = False
    service_tier: str = "standard"
    context_window: str | None = "0-200k"
    inference_geo: str | None = "global"
    cache_1h: bool = False
    # Web search requests per USD of model spend.
    web_search: Decimal = Decimal("0")
    # OpenRouter: inference billed by the underlying provider through the member's own key.
    byok: bool = False
    # Share of the completion tokens spent reasoning.
    reasoning: Decimal = Decimal("0")
    # A later model the stream switches to on a date.
    switch: tuple[date, str] | None = None
    # OpenAI `user_id` / Cursor e-mail of the person behind the usage, when not the principal.
    owner: str | None = None
    # Cursor: the service account the usage runs under.
    service_account: tuple[str, str] | None = None
    # False for traffic that does not follow the working week (a customer-facing bot).
    weekly: bool = True
    # From a date on, this much of `base` moves to another stream.
    handoff: tuple[date, Decimal] | None = None

    def active(self, day: date) -> bool:
        return (self.start is None or day >= self.start) and (self.end is None or day < self.end)

    def model_on(self, day: date) -> str:
        if self.switch is not None and day >= self.switch[0]:
            return self.switch[1]
        return self.model

    def amount(self, version: int, day: date, provider: str, account: str) -> Decimal:
        if not self.active(day):
            return Decimal("0")
        base = self.base
        if self.handoff is not None and day >= self.handoff[0]:
            base -= self.handoff[1]
        value = (
            base
            * (weekday_factor(day) if self.weekly else Decimal("1"))
            * growth(day)
            * noise(version, day, provider, account, self.principal + self.model)
            * ramp(day, self.start, self.ramp_days)
        )
        for story in self.stories:
            value *= story.factor_on(day)
        return value


@dataclass(frozen=True)
class Workspace:
    external_id: str
    name: str
    created_at: date
    archived_at: date | None = None
    # Answers the member and key listings with this status, as an archived workspace can.
    refuses_listing: int | None = None


@dataclass(frozen=True)
class User:
    external_id: str
    email: str
    name: str
    role: str
    added_at: date


@dataclass(frozen=True)
class Key:
    external_id: str
    name: str
    workspace: str | None
    owner: str | None
    created_at: date
    status: str = "active"
    expires_at: date | None = None
    # OpenAI: the key belongs to a service account instead of a user.
    service_account: tuple[str, str] | None = None


@dataclass(frozen=True)
class Activity:
    """OpenAI non-completions usage: one family on one key, priced per unit."""

    family: str
    model: str | None
    workspace: str
    api_key: str | None
    user: str | None
    # Units per weekday at the growth reference, and what each costs.
    quantity: Decimal
    unit_price: Decimal
    # The costs report line item the money is billed under; None when the family is free.
    line_item: str | None
    requests_per_unit: Decimal = Decimal("0")
    detail: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Account:
    provider: str
    # Stable account id the hashed values use; database ids differ between builds.
    key: str
    label: str
    external_id: str | None
    workspaces: tuple[Workspace, ...] = ()
    users: tuple[User, ...] = ()
    members: tuple[tuple[str, str, str], ...] = ()
    keys: tuple[Key, ...] = ()
    streams: tuple[Stream, ...] = ()
    activities: tuple[Activity, ...] = ()
    settings: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Budget:
    provider: str
    scope_kind: str
    scope_id: str
    state: Literal["healthy", "near_limit", "exceeded"]


TEAM_GROWTH = date(2026, 7, 6)
# Model moves made before Anthropic retired the old model (Claude Haiku 3.5 on 2026-02-19,
# Claude Sonnet 4 on 2026-06-15, Claude Opus 4.1 on 2026-08-05), so no request in the sample
# reaches a retired model while older months still show them.
HAIKU_UPGRADE = date(2026, 2, 9)
SONNET_UPGRADE = date(2026, 5, 4)
OPUS_UPGRADE = date(2026, 7, 27)
LEGACY_ARCHIVED = date(2026, 3, 2)
TRIAL_EXPIRED = date(2026, 9, 1)
EVE_JOINED = date(2026, 5, 11)
COPILOT_V2 = date(2026, 8, 24)
VOICE_PILOT_ARCHIVED = date(2026, 2, 2)
LONG_AGO = date(2025, 3, 3)

ANTHROPIC = Account(
    provider=ANTHROPIC_ID,
    key="acme",
    label="Acme",
    external_id="org_demo_acme",
    workspaces=(
        Workspace("wrkspc_demo_production", "Production", date(2025, 3, 3)),
        Workspace("wrkspc_demo_research", "Research", date(2025, 4, 7)),
        Workspace(
            "wrkspc_demo_legacy",
            "Legacy pilots",
            date(2025, 2, 3),
            archived_at=LEGACY_ARCHIVED,
            refuses_listing=404,
        ),
    ),
    users=(
        User("user_demo_ana", "ana@sample.example", "Ana Souza", "admin", LONG_AGO),
        User("user_demo_bruno", "bruno@sample.example", "Bruno Lima", "developer", LONG_AGO),
        User("user_demo_carla", "carla@sample.example", "Carla Mendes", "developer", LONG_AGO),
        User("user_demo_dan", "dan@sample.example", "Dan Ortiz", "billing", LONG_AGO),
        User("user_demo_eve", "eve@sample.example", "Eve Tanaka", "developer", EVE_JOINED),
    ),
    members=(
        ("wrkspc_demo_production", "user_demo_ana", "workspace_admin"),
        ("wrkspc_demo_production", "user_demo_bruno", "workspace_developer"),
        ("wrkspc_demo_production", "user_demo_eve", "workspace_developer"),
        ("wrkspc_demo_research", "user_demo_carla", "workspace_admin"),
        ("wrkspc_demo_research", "user_demo_ana", "workspace_user"),
    ),
    keys=(
        Key(
            "apikey_demo_prod_chat",
            "prod-chat",
            "wrkspc_demo_production",
            "user_demo_ana",
            LONG_AGO,
        ),
        Key(
            "apikey_demo_prod_agent",
            "prod-agent",
            "wrkspc_demo_production",
            "user_demo_bruno",
            LONG_AGO,
        ),
        Key(
            "apikey_demo_prod_batch",
            "prod-batch",
            "wrkspc_demo_production",
            "user_demo_bruno",
            LONG_AGO,
        ),
        Key(
            "apikey_demo_research_eval",
            "research-eval",
            "wrkspc_demo_research",
            "user_demo_carla",
            LONG_AGO,
        ),
        Key(
            "apikey_demo_research_notebook",
            "research-notebook",
            "wrkspc_demo_research",
            "user_demo_carla",
            LONG_AGO,
        ),
        Key(
            "apikey_demo_research_trial",
            "research-trial",
            "wrkspc_demo_research",
            "user_demo_eve",
            EVE_JOINED,
            status="expired",
            expires_at=TRIAL_EXPIRED,
        ),
        Key(
            "apikey_demo_legacy_pilot",
            "legacy-pilot",
            "wrkspc_demo_legacy",
            "user_demo_dan",
            date(2025, 2, 3),
            status="archived",
        ),
    ),
    streams=(
        Stream(
            "apikey_demo_prod_chat",
            "wrkspc_demo_production",
            "claude-sonnet-4",
            Decimal("48"),
            inference_geo="us",
            switch=(SONNET_UPGRADE, "claude-sonnet-4-5"),
        ),
        Stream(
            "apikey_demo_prod_agent",
            "wrkspc_demo_production",
            "claude-opus-4-1",
            Decimal("62"),
            stories=(AGENT_RETRY_LOOP,),
            cache_1h=True,
            switch=(OPUS_UPGRADE, "claude-opus-5"),
        ),
        Stream(
            "apikey_demo_prod_agent",
            "wrkspc_demo_production",
            "claude-opus-4-1",
            Decimal("8"),
            stories=(AGENT_RETRY_LOOP,),
            context_window="200k-1M",
            cache_1h=True,
            switch=(OPUS_UPGRADE, "claude-opus-5"),
        ),
        Stream(
            "apikey_demo_prod_batch",
            "wrkspc_demo_production",
            "claude-haiku-3-5",
            Decimal("14"),
            service_tier="batch",
            switch=(HAIKU_UPGRADE, "claude-haiku-4-5"),
        ),
        Stream(
            "apikey_demo_research_eval",
            "wrkspc_demo_research",
            "claude-opus-4-1",
            Decimal("30"),
            switch=(OPUS_UPGRADE, "claude-opus-5"),
        ),
        Stream(
            "apikey_demo_research_notebook",
            "wrkspc_demo_research",
            "claude-sonnet-4-5",
            Decimal("12"),
            web_search=Decimal("4"),
        ),
        Stream(
            "apikey_demo_research_trial",
            "wrkspc_demo_research",
            "claude-sonnet-4-5",
            Decimal("9"),
            start=EVE_JOINED,
            end=TRIAL_EXPIRED,
            ramp_days=14,
        ),
        Stream(
            "apikey_demo_legacy_pilot",
            "wrkspc_demo_legacy",
            "claude-sonnet-4",
            Decimal("16"),
            end=LEGACY_ARCHIVED,
        ),
        # A key deleted from the console: the usage report still names it, the inventory
        # no longer lists it.
        Stream(
            "apikey_demo_deleted_ci",
            "wrkspc_demo_production",
            "claude-haiku-3-5",
            Decimal("3"),
            switch=(HAIKU_UPGRADE, "claude-haiku-4-5"),
        ),
        Stream(
            "user_demo_carla",
            "wrkspc_demo_research",
            "claude-opus-4-1",
            Decimal("9"),
            stories=(CLAUDE_CODE_MIGRATION,),
            login=True,
            switch=(OPUS_UPGRADE, "claude-opus-5"),
        ),
        Stream(
            "user_demo_bruno",
            "wrkspc_demo_production",
            "claude-sonnet-4-5",
            Decimal("6"),
            login=True,
        ),
        Stream(
            "user_demo_eve",
            "wrkspc_demo_production",
            "claude-sonnet-4-5",
            Decimal("5"),
            start=EVE_JOINED,
            ramp_days=21,
            login=True,
        ),
    ),
)

OPENROUTER_WORKSPACE = "or-ws-demo-platform"
# A personal OpenRouter account: keys and workspaces, but the member listings answer 404 and
# 403, so the sample carries no OpenRouter users.
OPENROUTER = Account(
    provider=OPENROUTER_ID,
    key="acme",
    label="Acme",
    external_id=None,
    workspaces=(Workspace(OPENROUTER_WORKSPACE, "Platform", date(2025, 5, 5)),),
    keys=(
        Key("or_demo_gateway", "gateway", OPENROUTER_WORKSPACE, None, date(2025, 5, 12)),
        Key("or_demo_experiments", "experiments", OPENROUTER_WORKSPACE, None, date(2025, 6, 2)),
        Key("or_demo_ci", "ci", OPENROUTER_WORKSPACE, None, date(2025, 6, 2)),
        Key("or_demo_byok_research", "byok-research", OPENROUTER_WORKSPACE, None, date(2025, 8, 4)),
        Key(
            "or_demo_ci_legacy",
            "ci-legacy",
            OPENROUTER_WORKSPACE,
            None,
            date(2025, 5, 12),
            status="disabled",
        ),
    ),
    streams=(
        Stream(
            "or_demo_gateway",
            OPENROUTER_WORKSPACE,
            "openai/gpt-5.2",
            Decimal("18"),
            stories=(GATEWAY_OUTAGE,),
            reasoning=Decimal("0.25"),
        ),
        Stream(
            "or_demo_gateway",
            OPENROUTER_WORKSPACE,
            "anthropic/claude-sonnet-4.6",
            Decimal("10"),
            stories=(GATEWAY_OUTAGE,),
        ),
        Stream(
            "or_demo_experiments",
            OPENROUTER_WORKSPACE,
            "x-ai/grok-4.6",
            Decimal("7"),
            reasoning=Decimal("0.4"),
        ),
        Stream(
            "or_demo_experiments", OPENROUTER_WORKSPACE, "mistralai/devstral-medium", Decimal("2")
        ),
        # A regression suite still pinned to Claude Sonnet 4: Anthropic retired it on its own
        # API, and the request keeps resolving through another OpenRouter provider, so the
        # catalog reads its later days as Deprecated.
        Stream(
            "or_demo_experiments", OPENROUTER_WORKSPACE, "anthropic/claude-sonnet-4", Decimal("3")
        ),
        Stream("or_demo_ci", OPENROUTER_WORKSPACE, "openai/gpt-4o-mini", Decimal("4")),
        Stream(
            "or_demo_byok_research",
            OPENROUTER_WORKSPACE,
            "anthropic/claude-sonnet-4.6",
            Decimal("15"),
            byok=True,
        ),
    ),
)
# Late requests the control total already counts and the grouped report does not yet: the
# one deliberate gap Reconcile shows, on the last reported day.
OPENROUTER_LATE_USAGE = Decimal("4.20")

OPENAI_PLATFORM = Account(
    provider=OPENAI_ID,
    key="platform",
    label="Acme Platform",
    external_id="org-demoacmeplatform",
    workspaces=(
        Workspace("proj_demo_support", "Support copilot", date(2025, 4, 14)),
        Workspace("proj_demo_search", "Search", date(2025, 6, 9)),
        Workspace(
            "proj_demo_voice",
            "Voice pilot",
            date(2025, 5, 5),
            archived_at=VOICE_PILOT_ARCHIVED,
            refuses_listing=403,
        ),
    ),
    users=(
        User("user-demo-ana", "ana@sample.example", "Ana Souza", "owner", LONG_AGO),
        User("user-demo-fabio", "fabio@sample.example", "Fabio Reis", "member", LONG_AGO),
        User("user-demo-gina", "gina@sample.example", "Gina Park", "member", date(2026, 8, 3)),
    ),
    members=(
        ("proj_demo_support", "user-demo-ana", "owner"),
        ("proj_demo_support", "user-demo-gina", "member"),
        ("proj_demo_search", "user-demo-fabio", "owner"),
        ("proj_demo_search", "user-demo-ana", "member"),
    ),
    keys=(
        Key(
            "key_demo_support_prod", "support-prod", "proj_demo_support", "user-demo-ana", LONG_AGO
        ),
        Key(
            "key_demo_support_v2",
            "support-copilot-v2",
            "proj_demo_support",
            "user-demo-gina",
            COPILOT_V2,
        ),
        Key(
            "key_demo_search_indexer",
            "search-indexer",
            "proj_demo_search",
            "user-demo-fabio",
            LONG_AGO,
        ),
        Key(
            "key_demo_eval_runner",
            "eval-runner",
            "proj_demo_search",
            "svc_demo_eval",
            LONG_AGO,
            service_account=("svc_demo_eval", "eval-bot"),
        ),
    ),
    streams=(
        # The support bot answers customers every day of the week. On `COPILOT_V2` part of
        # its traffic moves to the new key, so the key is a new principal while the project
        # and the organization keep their level.
        Stream(
            "key_demo_support_prod",
            "proj_demo_support",
            "gpt-5.2",
            Decimal("70"),
            web_search=Decimal("3"),
            owner="user-demo-ana",
            weekly=False,
            handoff=(COPILOT_V2, Decimal("22")),
        ),
        Stream(
            "key_demo_support_v2",
            "proj_demo_support",
            "gpt-5.2",
            Decimal("22"),
            start=COPILOT_V2,
            owner="user-demo-gina",
            weekly=False,
        ),
        Stream(
            "key_demo_search_indexer",
            "proj_demo_search",
            "gpt-4o-mini",
            Decimal("14"),
            owner="user-demo-fabio",
        ),
        Stream(
            "key_demo_eval_runner",
            "proj_demo_search",
            "gpt-4.1-nano-2025-04-14",
            Decimal("6"),
            owner="svc_demo_eval",
        ),
        # The archived project's key: its listing answers 403, so the key stays unnamed.
        Stream(
            "key_demo_voice_pilot",
            "proj_demo_voice",
            "gpt-4o",
            Decimal("8"),
            end=VOICE_PILOT_ARCHIVED,
            owner="user-demo-ana",
        ),
    ),
    activities=(
        Activity(
            "images",
            "gpt-image-1",
            "proj_demo_support",
            "key_demo_support_prod",
            "user-demo-ana",
            quantity=Decimal("40"),
            unit_price=Decimal("0.04"),
            line_item="gpt-image-1, image generation",
            requests_per_unit=Decimal("0.5"),
            detail={"size": "1024x1024", "source": "image.generation"},
        ),
        Activity(
            "embeddings",
            "text-embedding-3-large",
            "proj_demo_search",
            "key_demo_search_indexer",
            "user-demo-fabio",
            quantity=Decimal("6000000"),
            unit_price=Decimal("0.00000013"),
            line_item="text-embedding-3-large",
            requests_per_unit=Decimal("0.0005"),
        ),
        Activity(
            "moderations",
            "omni-moderation-latest",
            "proj_demo_support",
            "key_demo_support_prod",
            "user-demo-ana",
            quantity=Decimal("2000000"),
            unit_price=Decimal("0"),
            line_item=None,
            requests_per_unit=Decimal("0.0004"),
        ),
        Activity(
            "audio_transcriptions",
            "whisper-1",
            "proj_demo_support",
            "key_demo_support_prod",
            "user-demo-ana",
            quantity=Decimal("1200"),
            unit_price=Decimal("0.0001"),
            line_item="whisper-1",
            requests_per_unit=Decimal("0.02"),
        ),
        # Storage OpenAI bills to the project, not to a key.
        Activity(
            "vector_stores",
            None,
            "proj_demo_search",
            None,
            None,
            quantity=Decimal("3200000000"),
            unit_price=Decimal("0.0000000001"),
            line_item="vector store storage",
        ),
    ),
)

OPENAI_LABS = Account(
    provider=OPENAI_ID,
    key="labs",
    label="Acme Labs",
    external_id="org-demoacmelabs",
    workspaces=(Workspace("proj_demo_labs", "Labs", date(2025, 7, 7)),),
    users=(User("user-demo-ana-labs", "ana@sample.example", "Ana Souza", "owner", LONG_AGO),),
    members=(("proj_demo_labs", "user-demo-ana-labs", "owner"),),
    keys=(
        Key(
            "key_demo_labs_notebook",
            "labs-notebook",
            "proj_demo_labs",
            "user-demo-ana-labs",
            date(2025, 7, 7),
        ),
    ),
    streams=(
        Stream(
            "key_demo_labs_notebook",
            "proj_demo_labs",
            "gpt-5.2",
            Decimal("9"),
            owner="user-demo-ana-labs",
        ),
    ),
)


def _cursor_member(email: str, model: str, base: str, start: date | None = None) -> Stream:
    return Stream(email, None, model, Decimal(base), start=start, ramp_days=21 if start else 0)


CURSOR = Account(
    provider=CURSOR_ID,
    key="acme",
    label="Acme",
    external_id=None,
    users=(
        User("cur_demo_ana", "ana@sample.example", "Ana Souza", "owner", LONG_AGO),
        User("cur_demo_bruno", "bruno@sample.example", "Bruno Lima", "member", LONG_AGO),
        User("cur_demo_carla", "carla@sample.example", "Carla Mendes", "member", LONG_AGO),
        User("cur_demo_eve", "eve@sample.example", "Eve Tanaka", "member", EVE_JOINED),
        User("cur_demo_hugo", "hugo@sample.example", "Hugo Alves", "member", TEAM_GROWTH),
        User("cur_demo_ivy", "ivy@sample.example", "Ivy Chen", "member", TEAM_GROWTH),
        User("cur_demo_jon", "jon@sample.example", "Jon Reyes", "member", TEAM_GROWTH),
    ),
    streams=(
        _cursor_member("ana@sample.example", "claude-sonnet-4-5", "4"),
        _cursor_member("bruno@sample.example", "claude-sonnet-4-5", "7"),
        _cursor_member("bruno@sample.example", "gpt-5.2", "2"),
        _cursor_member("carla@sample.example", "composer-2", "5"),
        _cursor_member("eve@sample.example", "claude-sonnet-4-5", "5", EVE_JOINED),
        _cursor_member("hugo@sample.example", "gpt-5.2", "4", TEAM_GROWTH),
        _cursor_member("ivy@sample.example", "claude-sonnet-4-5", "4", TEAM_GROWTH),
        _cursor_member("jon@sample.example", "composer-2", "3", TEAM_GROWTH),
        Stream(
            "sa_demo_bugbot",
            None,
            "claude-sonnet-4-5",
            Decimal("3"),
            owner="bruno@sample.example",
            service_account=("sa_demo_bugbot", "Bugbot CI"),
        ),
    ),
    settings={"seat_price_usd": 40.0, "include_included_in_business": True},
)
# What each Cursor seat includes per month before usage is billed as overage.
CURSOR_INCLUDED_USD = Decimal("20")

ACCOUNTS = (ANTHROPIC, OPENROUTER, OPENAI_PLATFORM, OPENAI_LABS, CURSOR)
PROVIDERS = (ANTHROPIC_ID, OPENROUTER_ID, OPENAI_ID, CURSOR_ID)


BUDGETS = (
    Budget(ANTHROPIC_ID, "org", "__org__", "near_limit"),
    Budget(ANTHROPIC_ID, "workspace", "wrkspc_demo_research", "healthy"),
    Budget(OPENAI_ID, "org", "__org__", "exceeded"),
    Budget(OPENROUTER_ID, "org", "__org__", "healthy"),
)


@dataclass(frozen=True)
class Failure:
    """A provider call that answers 503 in one daily cycle of one account, `attempts` times in
    a row: the cycle tries a step three times, so three fail the cycle and fewer recover
    inside it."""

    provider: str
    account: str
    days_ago: int
    call: str
    attempts: int


FAILURES = (
    Failure(OPENROUTER_ID, "acme", 2, "analytics_cost_pages", 3),
    Failure(ANTHROPIC_ID, "acme", 1, "usage_report_pages", 1),
)
# Daily cycles before the latest one, oldest first; the backfill runs the day before them.
DAILY_CYCLES = 3
