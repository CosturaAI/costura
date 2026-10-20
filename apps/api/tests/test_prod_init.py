"""`scripts/prod-init.sh`: the production .env it writes from `.env.example`."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _init(tmp_path: Path, *args: str, google_secret: str = "") -> subprocess.CompletedProcess[str]:
    (tmp_path / "scripts").mkdir()
    for script in ("prod-init.sh", "prod-password.sh"):
        shutil.copy(ROOT / "scripts" / script, tmp_path / "scripts" / script)
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    env = {key: value for key, value in os.environ.items() if key != "GOOGLE_CLIENT_SECRET"}
    if google_secret:
        env["GOOGLE_CLIENT_SECRET"] = google_secret
    return subprocess.run(
        ["bash", str(tmp_path / "scripts" / "prod-init.sh"), *args],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )


def _values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value
    return values


def test_init_leaves_the_compose_variables_to_the_compose_file(tmp_path: Path) -> None:
    done = _init(tmp_path, "--email", "ops@example.com", "--host", "costura.example.com")
    assert done.returncode == 0, done.stderr
    text = (tmp_path / ".env").read_text()
    values = _values(tmp_path / ".env")
    for name in ("COSTURA_ENV", "DATABASE_URL", "TEST_DATABASE_URL", "COSTURA_API_URL"):
        assert name not in values
        assert f"# {name}: set by docker-compose.prod.yml" in text
    assert "costura:costura@" not in text
    assert values["COSTURA_WEB_PUBLIC_URL"] == "https://costura.example.com"
    assert values["GOOGLE_CLIENT_ID"] == "" and values["GOOGLE_CLIENT_SECRET"] == ""


def test_init_writes_the_google_client_without_printing_the_secret(tmp_path: Path) -> None:
    done = _init(
        tmp_path,
        "--email",
        "ops@example.com",
        "--host",
        "costura.example.com",
        "--google-client-id",
        "123.apps.googleusercontent.com",
        google_secret="GOCSPX-test-secret",
    )
    assert done.returncode == 0, done.stderr
    values = _values(tmp_path / ".env")
    assert values["GOOGLE_CLIENT_ID"] == "123.apps.googleusercontent.com"
    assert values["GOOGLE_CLIENT_SECRET"] == "GOCSPX-test-secret"
    assert "GOCSPX-test-secret" not in done.stdout + done.stderr


@pytest.mark.parametrize(
    ("client_id", "message"),
    [
        ("123.apps.googleusercontent.com", "needs the client secret"),
        ("https://bad/id", "is the client ID from the Google console"),
    ],
)
def test_init_refuses_an_incomplete_google_client(
    tmp_path: Path, client_id: str, message: str
) -> None:
    done = _init(tmp_path, "--email", "ops@example.com", "--google-client-id", client_id)
    assert done.returncode == 1
    assert message in done.stderr
    assert not (tmp_path / ".env").exists()
