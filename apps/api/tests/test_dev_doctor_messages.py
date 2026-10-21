"""Doctor diagnostics name remedies without needing Docker or occupied host ports."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BASH = shutil.which("bash")


def _tool(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def doctor(tmp_path: Path) -> tuple[Path, Path]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(ROOT / "scripts/doctor.sh", scripts / "doctor.sh")
    tools = tmp_path / "bin"
    tools.mkdir()
    _tool(tools, "dirname", 'printf "%s\\n" "${1%/*}"')
    _tool(tools, "head", 'IFS= read -r line; printf "%s\\n" "$line"')
    _tool(tools, "ps", 'printf "%s\\n" python3')
    _tool(
        tools,
        "lsof",
        '[[ " $* " == *" -iTCP:${TEST_BUSY_PORT:-none} "* ]] || exit 1\n'
        'if [[ " $* " == *" -t "* ]]; then printf "%s\\n" 12345; fi',
    )
    return tmp_path, tools


def _output(doctor: tuple[Path, Path], **changes: str) -> str:
    root, tools = doctor
    assert BASH is not None
    environment = dict(changes)
    tools_path = tools.as_posix()
    if os.name == "nt":
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        tools_path = f"/{tools_path[0].lower()}{tools_path[2:]}"
    result = subprocess.run(
        [BASH, "-c", 'PATH="$1"; source "$0"', "scripts/doctor.sh", tools_path],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result.stdout


def test_missing_docker_names_the_install_link(doctor: tuple[Path, Path]) -> None:
    assert (
        "Docker is not installed; install it from https://docs.docker.com/get-docker/"
        in _output(doctor)
    )


def test_stopped_docker_names_how_to_start_it(doctor: tuple[Path, Path]) -> None:
    _tool(doctor[1], "docker", "exit 1")
    assert (
        "the Docker daemon is not running; start Docker Desktop or the docker service"
        in _output(doctor)
    )


@pytest.mark.parametrize("port", ["8000", "3000"])
def test_busy_port_names_its_listener_and_stop_command(
    doctor: tuple[Path, Path], port: str
) -> None:
    assert (
        f"port {port} is already in use by python3 (pid 12345); stop it with: kill 12345"
        in _output(doctor, TEST_BUSY_PORT=port)
    )


def test_busy_port_keeps_the_fallback_without_lsof(doctor: tuple[Path, Path]) -> None:
    tools = doctor[1]
    (tools / "lsof").unlink()
    _tool(tools, "python3", '[[ "${@: -1}" == 8000 ]]')
    output = _output(doctor)
    assert "error: port 8000 is already in use\n" in output
    assert "stop it with: kill" not in output
