#!/usr/bin/env python3
"""Validate that coverage reports are fresh, complete, and branch-sensitive."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
WEB_ROOT = ROOT / "apps" / "web"
API_REPORT = API_ROOT / "coverage.json"
WEB_REPORT = WEB_ROOT / "coverage" / "lcov.info"
API_BRANCH_FLOOR = 83.0
WEB_EXCLUDED = {
    "src/components/ui/badge.tsx",
    "src/components/ui/button.tsx",
    "src/components/ui/card.tsx",
    "src/components/ui/checkbox.tsx",
    "src/components/ui/input.tsx",
    "src/components/ui/table.tsx",
    "src/components/ui/tabs.tsx",
}


def fail(messages: list[str]) -> None:
    if messages:
        raise SystemExit("coverage validation failed:\n- " + "\n- ".join(messages))


def api_errors() -> list[str]:
    if not API_REPORT.is_file():
        return [f"missing {API_REPORT.relative_to(ROOT)}"]
    report = json.loads(API_REPORT.read_text())
    branch_percent = float(report["totals"]["percent_branches_covered"])
    errors = []
    if branch_percent < API_BRANCH_FLOOR:
        errors.append(f"API branch coverage {branch_percent:.2f}% is below {API_BRANCH_FLOOR:.0f}%")
    reported = {Path(name).as_posix() for name in report["files"]}
    eligible = {
        path.relative_to(API_ROOT).as_posix()
        for path in (API_ROOT / "costura").rglob("*.py")
        if "__pycache__" not in path.parts
    }
    missing = sorted(eligible - reported)
    if missing:
        errors.append("API files absent from coverage.json: " + ", ".join(missing))
    return errors


def web_errors() -> list[str]:
    if not WEB_REPORT.is_file():
        return [f"missing {WEB_REPORT.relative_to(ROOT)}"]
    records = {
        line.removeprefix("SF:").strip()
        for line in WEB_REPORT.read_text().splitlines()
        if line.startswith("SF:")
    }
    errors = []
    stale = sorted(name for name in records if not (WEB_ROOT / name).is_file())
    if stale:
        errors.append("LCOV records reference nonexistent files: " + ", ".join(stale))
    eligible = {
        path.relative_to(WEB_ROOT).as_posix()
        for path in (WEB_ROOT / "src").rglob("*")
        if path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
        and "src/test/" not in path.relative_to(WEB_ROOT).as_posix()
        and path.relative_to(WEB_ROOT).as_posix() not in WEB_EXCLUDED
    }
    missing = sorted(eligible - records)
    if missing:
        errors.append("web files absent from LCOV: " + ", ".join(missing))
    return errors


if __name__ == "__main__":
    failures = [*api_errors(), *web_errors()]
    fail(failures)
    print("coverage reports complete; API branch coverage is at least 83%")
