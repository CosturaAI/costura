"""Pins that keep the open-source package, Compose contract, and docs in step."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_version_matches_across_packages() -> None:
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    version = manifest["."]
    assert (ROOT / "version.txt").read_text().strip() == version
    pyproject = (ROOT / "apps/api/pyproject.toml").read_text()
    assert f'version = "{version}"' in pyproject
    assert 'requires-python = ">=3.14,<3.15"' in pyproject
    package = json.loads((ROOT / "apps/web/package.json").read_text())
    assert package["version"] == version
    assert package["engines"]["node"] == ">=26 <27"


def test_packaged_licenses_match_the_repository_copies() -> None:
    legal = ROOT / "apps/api/costura/legal"
    assert (legal / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert (legal / "NOTICE").read_bytes() == (ROOT / "NOTICE").read_bytes()
    for name in (
        "shadcn-MIT.txt",
        "lucide-ISC.txt",
        "fonts-OFL-1.1.txt",
        "psycopg-LGPL-3.0.txt",
        "psycopg-GPL-3.0.txt",
    ):
        assert (legal / name).read_bytes() == (ROOT / "third_party/licenses" / name).read_bytes()
    fonts = (ROOT / "third_party/licenses/fonts-OFL-1.1.txt").read_text()
    assert "[fullname]" not in fonts
    assert "The Inter Project Authors" in fonts
    assert "The JetBrains Mono Project Authors" in fonts


def test_web_image_ships_npm_notices() -> None:
    dockerfile = (ROOT / "apps/web/Dockerfile").read_text()
    assert "scripts/collect-licenses.mjs /app/npm-THIRD-PARTY.txt" in dockerfile
    assert "/app/npm-THIRD-PARTY.txt /app/licenses/third-party/" in dockerfile


def test_production_compose_forwards_runtime_settings() -> None:
    text = (ROOT / "docker-compose.prod.yml").read_text()
    for name in (
        "ANTHROPIC_BASE_URL",
        "CLAUDE_AI_BASE_URL",
        "CODEX_BASE_URL",
        "OPENROUTER_BASE_URL",
        "OPENAI_BASE_URL",
        "CURSOR_BASE_URL",
        "COSTURA_DEMO_REFRESH",
        "COSTURA_RATE_LIMIT_AUTH",
        "COSTURA_RATE_LIMIT_WRITE",
        "COSTURA_RATE_LIMIT_DEMO",
        "COSTURA_RAW_PAGE_RETENTION_DAYS",
        "COSTURA_RUN_RETENTION_DAYS",
        "COSTURA_SIGN_UP",
        "COSTURA_ALLOWED_EMAIL_DOMAINS",
    ):
        assert name in text
    assert "COSTURA_ACME_EMAIL" not in text
    assert ":-latest}" not in text
    assert text.count("${COSTURA_VERSION:?set COSTURA_VERSION in .env}") == 3
    env = (ROOT / ".env.example").read_text()
    version = json.loads((ROOT / ".release-please-manifest.json").read_text())["."]
    assert f"x-release-please-start-version\nCOSTURA_VERSION={version}\n" in env
    assert "ghcr.io/costuraai/costura-api:" in text
    assert "ghcr.io/costuraai/costura-web:" in text
    assert "ghcr.io/costuraai/costura-proxy:" in text


def test_documented_commands_exist() -> None:
    prod = (ROOT / ".just/prod.just").read_text()
    for recipe in ("backup ", "restore ", "up-local:", "smoke:", "secret-check:"):
        assert recipe in prod
    assert "save-previous" not in prod
    assert re.search(r"^rollback:", prod, re.MULTILINE) is None
    upgrade = (ROOT / "docs/operations/upgrade.md").read_text()
    backup = (ROOT / "docs/operations/backup-restore.md").read_text()
    assert "COSTURA_VERSION=" in upgrade
    assert "just prod::backup" in backup
    assert "just prod::secret-check" in backup
    assert "set -a && source .env" not in backup
