"""Check a production .env without printing a value: python3 scripts/prod-doctor-env.py .env

One line per problem, `error:` or `warning:`; exits 1 when any error was printed.
Needs only the Python standard library, like scripts/prod-init.sh.
"""

import re
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

MIN_OPERATOR_SECRET = 24
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def site_origin(address: str) -> tuple[str, str]:
    """The origin and host Caddy serves for COSTURA_SITE_ADDRESS."""
    if "://" not in address:
        address = f"https://{address}"
    parts = urlsplit(address)
    host = parts.hostname or ""
    origin = f"{parts.scheme}://{parts.netloc}"
    return origin, host


def resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
    except OSError:
        return False
    return True


def _release(values: dict[str, str]) -> list[str]:
    version = values.get("COSTURA_VERSION", "")
    if not version:
        return ["COSTURA_VERSION is empty; set the release to run, as in .env.example"]
    if version == "latest":
        return ["COSTURA_VERSION=latest is not a supported install; pin a release"]
    if re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", version) is None:
        return ["COSTURA_VERSION is not a release number such as 1.2.3 (no leading v)"]
    return []


def _addresses(values: dict[str, str], resolve) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    origin, host = site_origin(values.get("COSTURA_SITE_ADDRESS", "") or "http://localhost")
    for name in ("COSTURA_WEB_ORIGIN", "COSTURA_WEB_PUBLIC_URL"):
        value = values.get(name, "").rstrip("/")
        if name == "COSTURA_WEB_ORIGIN" and not value:
            value = "http://localhost"
        if value and value != origin:
            errors.append(f"{name} does not name the origin COSTURA_SITE_ADDRESS serves ({origin})")
    if not values.get("COSTURA_WEB_PUBLIC_URL"):
        warnings.append(
            f"COSTURA_WEB_PUBLIC_URL is empty; invitation and webhook links need it ({origin})"
        )
    if host in LOOPBACK:
        return errors, warnings
    if origin.startswith("http://"):
        warnings.append(
            "COSTURA_SITE_ADDRESS is plain http on a public host; browsers drop the session cookie"
        )
    elif not resolve(host):
        errors.append(
            f"{host} does not resolve; point its DNS at this host before Caddy asks for a "
            "certificate"
        )
    return errors, warnings


def _sign_in(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    operator_email = values.get("COSTURA_OPERATOR_EMAIL", "")
    operator_secret = values.get("COSTURA_OPERATOR_SECRET", "")
    operator = bool(operator_email) and len(operator_secret) >= MIN_OPERATOR_SECRET
    if (operator_email or operator_secret) and not operator:
        errors.append(
            "COSTURA_OPERATOR_EMAIL needs COSTURA_OPERATOR_SECRET of at least "
            f"{MIN_OPERATOR_SECRET} characters (just api::operator-secret, or openssl rand -hex 24)"
        )
    google_id = values.get("GOOGLE_CLIENT_ID", "")
    google_secret = values.get("GOOGLE_CLIENT_SECRET", "")
    google = bool(google_id and google_secret)
    if bool(google_id) != bool(google_secret):
        errors.append("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set together or not at all")
    if not operator and not google and not (operator_email or operator_secret):
        errors.append(
            "no sign-in method: set COSTURA_OPERATOR_EMAIL and COSTURA_OPERATOR_SECRET, "
            "or the Google client"
        )
    elif google and not operator:
        sign_up = values.get("COSTURA_SIGN_UP", "") or "invite_only"
        if sign_up == "invite_only" and not values.get("COSTURA_ALLOWED_EMAIL_DOMAINS"):
            errors.append(
                "only Google sign-in, invitation-only and no allowed domain: nobody can sign "
                "in first; keep the operator pair for the first login, or set "
                "COSTURA_ALLOWED_EMAIL_DOMAINS"
            )
    return errors


def check(values: dict[str, str], resolve=resolves) -> tuple[list[str], list[str]]:
    address_errors, warnings = _addresses(values, resolve)
    return _release(values) + address_errors + _sign_in(values), warnings


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else ".env")
    if not path.is_file():
        print(f"error: {path} does not exist; write it with just prod::init")
        return 1
    errors, warnings = check(read_env(path))
    for line in warnings:
        print(f"warning: {line}")
    for line in errors:
        print(f"error: {line}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
