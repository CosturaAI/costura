"""The development doctor reports database URLs that disagree with its port."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["DATABASE_URL", "TEST_DATABASE_URL"])
@pytest.mark.parametrize("port", [5432, 5433])
def test_database_url_port_matches_the_development_database(name: str, port: int) -> None:
    environment = os.environ.copy()
    for variable in ("DATABASE_URL", "TEST_DATABASE_URL", "COSTURA_DEV_DB_PORT"):
        environment.pop(variable, None)
    environment[name] = f"postgresql+psycopg://costura:costura@localhost:{port}/costura"

    result = subprocess.run(
        ["bash", "scripts/doctor.sh"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    if port == 5433:
        assert f"{name} uses port 5433" in result.stdout
        assert "run: just db::port 5432" in result.stdout
    else:
        assert f"{name} uses port" not in result.stdout
