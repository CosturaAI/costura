import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

MIN_OPERATOR_SECRET = 24
PROVIDER_BASE_URLS = (
    "anthropic_base_url",
    "claude_ai_base_url",
    "codex_base_url",
    "openrouter_base_url",
    "openai_base_url",
    "cursor_base_url",
    "copilot_base_url",
)
_SCHEDULE_AT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Repository root: apps/api/costura/config.py -> three levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Process configuration, read from environment variables and the repo-root `.env`."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    costura_env: Literal["development", "test", "production"]
    database_url: str
    # Threshold for the `costura` loggers in the API, the worker and the scheduler.
    costura_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Environment fallback keys for the `COSTURA_ORG` organization; stored credentials take
    # precedence. Anthropic: Admin API key (sk-ant-admin01-...).
    # OpenRouter: management key (sk-or-v1-...). OpenAI: admin key (sk-admin-...). Cursor:
    # team API key (key_...). Every sync client is read-only.
    anthropic_admin_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    claude_ai_api_key: SecretStr | None = None
    claude_ai_base_url: str = "https://api.anthropic.com"
    codex_admin_key: SecretStr | None = None
    codex_base_url: str = "https://api.chatgpt.com/v1/analytics/codex"
    codex_workspace_id: str | None = None
    openrouter_admin_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openai_admin_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    cursor_api_key: SecretStr | None = None
    cursor_base_url: str = "https://api.cursor.com"
    copilot_github_token: SecretStr | None = None
    copilot_base_url: str = "https://api.github.com"
    copilot_org: str | None = None

    # Fernet key (urlsafe base64, 32 bytes) that encrypts stored provider credentials.
    # `just api::secret-generate` prints one. Required by the scheduler and the connection
    # write routes; absent means credentials live only in ANTHROPIC_ADMIN_KEY.
    costura_secret_key: SecretStr | None = None
    # The key being rotated away from. Reads accept it while `just prod::secret-rotate`
    # rewrites the rows under COSTURA_SECRET_KEY; remove it once `secret-check` reports no row
    # on it.
    costura_secret_key_previous: SecretStr | None = None
    # Daily time (UTC, HH:MM) at which the scheduler runs every organization.
    costura_schedule_at: str = "06:00"
    # Rebuild the public sample organization at each daily pass when it is stale
    # (`costura.demo.refresh_if_stale`). Off by default; needs no provider key.
    costura_demo_refresh: bool = False

    # Organization that may use the environment fallback provider keys above.
    costura_org: str = "default"
    # Browser origin allowed to call the read API (the Next.js dev server by default).
    costura_web_origin: str = "http://localhost:3000"

    # Requests per minute per client address for the sign-in routes, the writes and the
    # public sample organization's reads (`costura.api.ratelimit`); 0 turns a bucket off.
    # A negative value is rejected so a typo cannot disable the limit.
    costura_rate_limit_auth: int = Field(default=20, ge=0)
    costura_rate_limit_write: int = Field(default=120, ge=0)
    costura_rate_limit_demo: int = Field(default=3000, ge=0)
    # Reads per minute per session (every GET under /api/v1 outside the sample), and provider
    # key stores (connect, add an account, replace a key) per minute per organization.
    costura_rate_limit_read: int = Field(default=1200, ge=0)
    costura_rate_limit_connect: int = Field(default=10, ge=0)

    # Peers allowed to set `X-Forwarded-For`: comma-separated IPs or CIDRs, or `*`.
    # Empty ignores the header. A trusted peer's client is the rightmost forwarded hop
    # that is not itself trusted (`*` takes the rightmost hop). Development writes use
    # that address and still require loopback; an untrusted header keeps them refused.
    costura_trusted_proxies: str = ""
    # Months a new connection imports, current month included; the daily run reads two.
    costura_backfill_months: int = Field(default=3, ge=2, le=13)
    # Days to keep raw `provider_report_pages`. 0 keeps them forever.
    costura_raw_page_retention_days: int = Field(default=90, ge=0)
    # Days to keep terminal scheduler runs and completed sync runs that the ledger no
    # longer references. 0 keeps them forever. Referenced sync runs stay.
    costura_run_retention_days: int = Field(default=90, ge=0)

    # Hosts an organization's signal webhook may post to, comma-separated (for Slack,
    # `hooks.slack.com`). Empty turns outbound delivery off: no webhook can be saved or sent.
    costura_webhook_hosts: str = ""

    # The HTTPS origin the browser reaches the web application at; invitation links, the
    # links in webhook messages and the Google sign-in callback are built from it.
    costura_web_public_url: str | None = None

    # Google OAuth web application credentials. The callback is the Next.js route at
    # `{COSTURA_WEB_PUBLIC_URL}/api/auth/google/callback`; incomplete or invalid configuration
    # leaves Google sign-in disabled without preventing startup.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # Both values are required; the secret is at least 24 characters.
    # `just api::operator-secret` prints one.
    costura_operator_email: str | None = None
    costura_operator_secret: SecretStr | None = None

    # Who may create an account with Google. Unset means `invite_only` in production and
    # `open` elsewhere. An address with a pending invitation is always accepted.
    costura_sign_up: Literal["open", "invite_only"] | None = None
    # Comma-separated e-mail domains allowed to sign up, such as `example.com`. Empty
    # applies `costura_sign_up` to every domain.
    costura_allowed_email_domains: str = ""

    @field_validator("costura_schedule_at")
    @classmethod
    def _schedule_at(cls, value: str) -> str:
        cleaned = value.strip()
        if _SCHEDULE_AT.fullmatch(cleaned) is None:
            raise ValueError("COSTURA_SCHEDULE_AT must be HH:MM in 24-hour UTC")
        return cleaned

    @property
    def webhook_hosts(self) -> frozenset[str]:
        return frozenset(
            host.strip().lower().rstrip(".")
            for host in self.costura_webhook_hosts.split(",")
            if host.strip()
        )

    @property
    def google_redirect_uri(self) -> str | None:
        value = (self.costura_web_public_url or "").rstrip("/")
        parsed = urlsplit(value)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or not parsed.netloc
            or (parsed.scheme != "https" and not local_http)
        ):
            return None
        return f"{value}/api/auth/google/callback"

    @property
    def google_available(self) -> bool:
        return bool(
            self.google_client_id and self.google_client_secret and self.google_redirect_uri
        )

    @property
    def normalized_operator_email(self) -> str | None:
        raw = (self.costura_operator_email or "").strip().lower()
        local, separator, domain = raw.partition("@")
        if not separator or not local or not domain or "@" in domain:
            return None
        return raw

    def operator_secret_value(self) -> str | None:
        secret = self.costura_operator_secret
        if secret is None:
            return None
        value = secret.get_secret_value()
        if len(value) < MIN_OPERATOR_SECRET:
            return None
        return value

    @property
    def operator_available(self) -> bool:
        return (
            self.normalized_operator_email is not None and self.operator_secret_value() is not None
        )

    @property
    def effective_sign_up(self) -> Literal["open", "invite_only"]:
        if self.costura_sign_up is not None:
            return self.costura_sign_up
        if self.costura_env == "production":
            return "invite_only"
        return "open"

    def allowed_email_domains(self) -> frozenset[str]:
        return frozenset(
            part.strip().lower()
            for part in self.costura_allowed_email_domains.split(",")
            if part.strip()
        )


EXAMPLE_DATABASE_PASSWORD = "costura"


def _database_password(url: str) -> str | None:
    try:
        return make_url(url).password
    except ArgumentError:
        return None


def production_warnings(settings: Settings) -> list[str]:
    """What a production API should log at startup without refusing to run."""
    if settings.costura_env != "production":
        return []
    if settings.operator_available and settings.google_available:
        return [
            "the deployment administrator sign-in is still enabled next to Google; once an "
            "owner can sign in with Google, remove COSTURA_OPERATOR_EMAIL and "
            "COSTURA_OPERATOR_SECRET and revoke that session"
        ]
    return []


def production_runtime_errors(settings: Settings) -> list[str]:
    """Why any production process must refuse to start. Empty outside production.

    The worker and the scheduler use this check. They do not serve sign-in, so they do not
    require an operator secret or Google credentials.
    """
    if settings.costura_env != "production":
        return []
    errors: list[str] = []
    if not settings.database_url.strip():
        errors.append("DATABASE_URL is required in production")
    elif _database_password(settings.database_url) == EXAMPLE_DATABASE_PASSWORD:
        errors.append("DATABASE_URL uses the example password `costura`; choose another")
    for name in PROVIDER_BASE_URLS:
        url = getattr(settings, name)
        if urlsplit(url).scheme != "https":
            errors.append(f"{name.upper()} must be an https:// URL in production")
    secret = settings.costura_secret_key
    value = "" if secret is None else secret.get_secret_value().strip()
    if not value:
        errors.append(
            "COSTURA_SECRET_KEY is required in production; "
            "generate one with `just api::secret-generate`"
        )
    else:
        try:
            Fernet(value.encode("ascii"))
        except (ValueError, TypeError) as exc:
            del exc
            errors.append(
                "COSTURA_SECRET_KEY is not a valid Fernet key; "
                "generate one with `just api::secret-generate`"
            )
    previous = settings.costura_secret_key_previous
    old = "" if previous is None else previous.get_secret_value().strip()
    if old:
        try:
            Fernet(old.encode("ascii"))
        except (ValueError, TypeError) as exc:
            del exc
            errors.append("COSTURA_SECRET_KEY_PREVIOUS is not a valid Fernet key")
    return errors


def production_startup_errors(settings: Settings) -> list[str]:
    """Why the API must refuse to start. Adds a sign-in method to the runtime checks."""
    errors = production_runtime_errors(settings)
    if settings.costura_env != "production":
        return errors
    google_id = (settings.google_client_id or "").strip()
    google_secret = ""
    if settings.google_client_secret is not None:
        google_secret = settings.google_client_secret.get_secret_value().strip()
    if google_id and google_secret and settings.google_redirect_uri is None:
        errors.append(
            "COSTURA_WEB_PUBLIC_URL must be an https origin (http only on localhost) "
            "when Google sign-in is configured"
        )
    if not settings.operator_available and not settings.google_available:
        errors.append(
            "production needs a sign-in method: COSTURA_OPERATOR_EMAIL with "
            "COSTURA_OPERATOR_SECRET (at least 24 characters), or Google sign-in"
        )
    return errors


def _refuse(errors: list[str]) -> None:
    if errors:
        raise RuntimeError("refusing to start: " + "; ".join(errors))


def require_production_runtime(settings: Settings | None = None) -> None:
    """Refuse to start a worker, scheduler, or migration when the database or key is unusable."""
    _refuse(production_runtime_errors(settings or get_settings()))


def require_production_config(settings: Settings | None = None) -> None:
    """Refuse to start the API when production is missing the secret, the database, or sign-in."""
    _refuse(production_startup_errors(settings or get_settings()))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
