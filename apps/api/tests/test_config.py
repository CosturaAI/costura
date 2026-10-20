"""Required, allowlisted process environment configuration."""

import subprocess

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from costura.config import (
    KEY_HINT,
    ConfigError,
    Settings,
    get_settings,
    production_runtime_errors,
    production_startup_errors,
    production_warnings,
    require_production_config,
    require_production_runtime,
)

VALID_KEY = Fernet.generate_key().decode("ascii")


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://unused", **values)  # type: ignore[arg-type]


def test_costura_env_is_required_and_nonempty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COSTURA_ENV")
    with pytest.raises(ValidationError, match="costura_env"):
        settings()
    monkeypatch.setenv("COSTURA_ENV", "")
    with pytest.raises(ValidationError, match="costura_env"):
        settings()


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_costura_env_accepts_only_named_environments(environment: str) -> None:
    assert settings(costura_env=environment).costura_env == environment

    with pytest.raises(ValidationError, match="costura_env"):
        settings(costura_env="staging")


def test_retention_defaults_to_ninety_days_and_rejects_a_negative() -> None:
    ready = settings(costura_env="test")
    assert ready.costura_raw_page_retention_days == 90
    assert ready.costura_run_retention_days == 90
    with pytest.raises(ValidationError, match="costura_raw_page_retention_days"):
        settings(costura_env="test", costura_raw_page_retention_days=-1)


def test_operator_mode_needs_an_email_and_a_24_character_secret() -> None:
    absent = settings(costura_env="production")
    assert absent.operator_available is False

    short = settings(
        costura_env="production",
        costura_operator_email="ops@example.com",
        costura_operator_secret=SecretStr("short-secret"),
    )
    assert short.operator_available is False

    ready = settings(
        costura_env="production",
        costura_operator_email="  Ops@Example.com ",
        costura_operator_secret=SecretStr("s" * 24),
    )
    assert ready.normalized_operator_email == "ops@example.com"
    assert ready.operator_available is True


def test_production_refuses_to_start_without_a_secret_or_database() -> None:
    with pytest.raises(RuntimeError, match="COSTURA_SECRET_KEY"):
        require_production_config(settings(costura_env="production", costura_secret_key=None))
    blank_database = Settings(
        _env_file=None,  # type: ignore[call-arg]
        costura_env="production",
        database_url="  ",
        costura_secret_key=SecretStr("present"),
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        require_production_config(blank_database)


def test_production_api_refuses_to_start_without_a_sign_in_method() -> None:
    with pytest.raises(RuntimeError, match="sign-in method"):
        require_production_config(
            settings(costura_env="production", costura_secret_key=SecretStr(VALID_KEY))
        )


def test_production_accepts_a_secret_and_an_operator() -> None:
    assert (
        production_startup_errors(
            settings(
                costura_env="production",
                costura_secret_key=SecretStr(VALID_KEY),
                costura_operator_email="ops@example.com",
                costura_operator_secret=SecretStr("s" * 24),
            )
        )
        == []
    )


def test_worker_starts_without_a_sign_in_method() -> None:
    assert (
        production_runtime_errors(
            settings(
                costura_env="production",
                costura_secret_key=SecretStr(VALID_KEY),
            )
        )
        == []
    )


def test_production_refuses_the_example_database_password() -> None:
    def with_url(url: str) -> Settings:
        return Settings(
            _env_file=None,  # type: ignore[call-arg]
            costura_env="production",
            database_url=url,
            costura_secret_key=SecretStr(VALID_KEY),
        )

    with pytest.raises(RuntimeError, match="example password"):
        require_production_runtime(with_url("postgresql+psycopg://app:costura@postgres:5432/db"))
    require_production_runtime(with_url("postgresql+psycopg://app:long-secret@postgres:5432/db"))
    require_production_runtime(with_url("not a url"))
    test_like = Settings(
        _env_file=None,  # type: ignore[call-arg]
        costura_env="test",
        database_url="postgresql+psycopg://costura:costura@localhost:5432/costura",
    )
    require_production_runtime(test_like)


def test_production_warns_while_the_operator_sits_next_to_google() -> None:
    operator = {
        "costura_operator_email": "ops@example.com",
        "costura_operator_secret": SecretStr("s" * 24),
    }
    google = {
        "google_client_id": "client",
        "google_client_secret": SecretStr("secret"),
        "costura_web_public_url": "https://costura.example.com",
    }
    both = settings(costura_env="production", **operator, **google)
    assert "COSTURA_OPERATOR_SECRET" in production_warnings(both)[0]
    assert production_warnings(settings(costura_env="production", **operator)) == []
    assert production_warnings(settings(costura_env="development", **operator, **google)) == []


def test_production_refuses_a_secret_that_is_not_fernet() -> None:
    broken = settings(
        costura_env="production",
        costura_secret_key=SecretStr("present"),
        costura_operator_email="ops@example.com",
        costura_operator_secret=SecretStr("s" * 24),
    )
    with pytest.raises(RuntimeError, match="Fernet"):
        require_production_runtime(broken)


def test_development_starts_without_a_secret_key() -> None:
    assert production_startup_errors(settings(costura_env="development")) == []


def test_production_refuses_google_without_a_sane_public_url() -> None:
    broken = settings(
        costura_env="production",
        costura_secret_key=SecretStr(VALID_KEY),
        google_client_id="client",
        google_client_secret=SecretStr("secret"),
        costura_web_public_url="http://costura.example.com",
    )
    with pytest.raises(RuntimeError, match="COSTURA_WEB_PUBLIC_URL"):
        require_production_config(broken)


def test_production_accepts_google_on_https_or_localhost() -> None:
    for public_url in ("https://costura.example.com", "http://localhost"):
        assert (
            production_startup_errors(
                settings(
                    costura_env="production",
                    costura_secret_key=SecretStr(VALID_KEY),
                    google_client_id="client",
                    google_client_secret=SecretStr("secret"),
                    costura_web_public_url=public_url,
                )
            )
            == []
        )


def test_the_api_refuses_to_start_but_imports_with_a_broken_production_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check runs in the app's lifespan: importing `costura.main` (a test, the OpenAPI
    export) does not trip it, starting the server does."""
    from fastapi.testclient import TestClient

    from costura.config import get_settings
    from costura.main import app

    monkeypatch.setattr(get_settings(), "costura_env", "production")
    monkeypatch.setattr(get_settings(), "costura_secret_key", None)
    with pytest.raises(RuntimeError, match="COSTURA_SECRET_KEY"), TestClient(app):
        pass


def test_production_refuses_a_plain_http_provider_base_url() -> None:
    plain = settings(
        costura_env="production",
        costura_secret_key=SecretStr(VALID_KEY),
        openrouter_base_url="http://openrouter.internal/api/v1",
    )
    assert production_runtime_errors(plain) == [
        "OPENROUTER_BASE_URL must be an https:// URL in production"
    ]
    development = settings(openrouter_base_url="http://localhost:9000/api/v1")
    assert production_runtime_errors(development) == []


def test_invalid_settings_refuse_in_one_line_without_the_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSTURA_SCHEDULE_AT", "6am")
    monkeypatch.setenv("COSTURA_BACKFILL_MONTHS", "hunter2")
    with pytest.raises(ConfigError) as refused:
        get_settings.__wrapped__()
    assert str(refused.value) == (
        "refusing to start: COSTURA_SCHEDULE_AT must be HH:MM in 24-hour UTC; "
        "COSTURA_BACKFILL_MONTHS: Input should be a valid integer, unable to parse string as "
        "an integer"
    )
    assert "6am" not in str(refused.value) and "hunter2" not in str(refused.value)


def test_the_key_hint_command_prints_a_fernet_key() -> None:
    command = KEY_HINT.split("development tools: ", 1)[1]
    key = subprocess.run(
        ["sh", "-c", command], check=True, capture_output=True, text=True
    ).stdout.strip()
    Fernet(key.encode("ascii"))
