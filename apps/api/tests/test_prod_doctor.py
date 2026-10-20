"""`scripts/prod-doctor-env.py`: the production .env checks behind `just prod::doctor`."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/prod-doctor-env.py"
_spec = importlib.util.spec_from_file_location("prod_doctor_env", SCRIPT)
assert _spec is not None and _spec.loader is not None
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)

PUBLIC = {
    "COSTURA_VERSION": "1.2.3",
    "COSTURA_SITE_ADDRESS": "costura.example.com",
    "COSTURA_WEB_ORIGIN": "https://costura.example.com",
    "COSTURA_WEB_PUBLIC_URL": "https://costura.example.com",
    "COSTURA_OPERATOR_EMAIL": "ops@example.com",
    "COSTURA_OPERATOR_SECRET": "x" * 32,
}


def _check(resolve: bool = True, **changes: str) -> tuple[list[str], list[str]]:
    return doctor.check({**PUBLIC, **changes}, resolve=lambda _host: resolve)


def test_a_consistent_public_install_passes() -> None:
    assert _check() == ([], [])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"COSTURA_VERSION": "latest"}, "latest is not a supported install"),
        ({"COSTURA_VERSION": "v1.2.3"}, "no leading v"),
        ({"COSTURA_WEB_ORIGIN": "https://other.example.com"}, "COSTURA_WEB_ORIGIN does not name"),
        ({"COSTURA_OPERATOR_SECRET": "short"}, "at least 24 characters"),
        ({"GOOGLE_CLIENT_ID": "id.apps.googleusercontent.com"}, "set together"),
        (
            {"COSTURA_OPERATOR_EMAIL": "", "COSTURA_OPERATOR_SECRET": ""},
            "no sign-in method",
        ),
        (
            {
                "COSTURA_OPERATOR_EMAIL": "",
                "COSTURA_OPERATOR_SECRET": "",
                "GOOGLE_CLIENT_ID": "id.apps.googleusercontent.com",
                "GOOGLE_CLIENT_SECRET": "s",
            },
            "nobody can sign in first",
        ),
    ],
)
def test_each_problem_is_one_error(changes: dict[str, str], message: str) -> None:
    errors, _ = _check(**changes)
    assert len(errors) == 1 and message in errors[0]


def test_google_only_passes_with_an_allowed_domain() -> None:
    errors, _ = _check(
        COSTURA_OPERATOR_EMAIL="",
        COSTURA_OPERATOR_SECRET="",
        GOOGLE_CLIENT_ID="id.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET="s",
        COSTURA_ALLOWED_EMAIL_DOMAINS="example.com",
    )
    assert errors == []


def test_a_public_host_must_resolve_and_the_errors_never_carry_a_secret() -> None:
    errors, _ = _check(resolve=False)
    assert errors == [
        "costura.example.com does not resolve; point its DNS at this host before Caddy asks "
        "for a certificate"
    ]
    assert all(PUBLIC["COSTURA_OPERATOR_SECRET"] not in line for line in errors)


def test_the_localhost_trial_needs_no_dns() -> None:
    errors, warnings = doctor.check(
        {
            "COSTURA_VERSION": "1.2.3",
            "COSTURA_SITE_ADDRESS": "http://localhost",
            "COSTURA_WEB_ORIGIN": "http://localhost",
            "COSTURA_WEB_PUBLIC_URL": "http://localhost",
            "COSTURA_OPERATOR_EMAIL": "ops@example.com",
            "COSTURA_OPERATOR_SECRET": "x" * 32,
        },
        resolve=lambda _host: pytest.fail("localhost is not resolved"),
    )
    assert (errors, warnings) == ([], [])
