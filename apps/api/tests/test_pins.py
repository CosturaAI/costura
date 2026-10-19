"""Every Python dependency in `apps/api/pyproject.toml` is pinned with `==`, so a release
builds from the same packages that CI tested. `requires-python` is a range by design."""

import re
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
EXACT_PIN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[0-9][0-9A-Za-z.+!-]*$"
)


def _requirements() -> list[str]:
    with PYPROJECT.open("rb") as handle:
        pyproject = tomllib.load(handle)
    requirements = list(pyproject["project"]["dependencies"])
    for group in pyproject.get("dependency-groups", {}).values():
        requirements.extend(entry for entry in group if isinstance(entry, str))
    requirements.extend(pyproject["build-system"]["requires"])
    return requirements


def test_every_dependency_is_pinned_with_an_exact_version() -> None:
    requirements = _requirements()
    assert requirements
    unpinned = [entry for entry in requirements if not EXACT_PIN.match(entry)]
    assert unpinned == [], f"range or missing pin: {unpinned}"
