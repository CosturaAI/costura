"""Rules the layout of `costura` keeps, checked on the source rather than by review."""

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "costura"
ROUTERS = PACKAGE / "api" / "routers"


def _sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_routers_do_not_translate_value_errors() -> None:
    """A domain refusal is a `DomainError` that the one handler in `costura.main` answers;
    a router catching `ValueError` hides a missing subclass and drifts per route."""
    offenders = [
        f"{path.relative_to(PACKAGE)}:{number}"
        for path in _sources(ROUTERS)
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if "except ValueError" in line or "except (ValueError" in line
    ]
    assert offenders == []


def test_routers_leave_the_commit_to_the_request_session() -> None:
    """`get_session` commits once when the route returns; a router commit splits one request
    into two transactions."""
    offenders = [
        f"{path.relative_to(PACKAGE)}:{number}"
        for path in _sources(ROUTERS)
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if ".commit()" in line
    ]
    assert offenders == []


REQUEST_PATH_COMMITS = {
    ("orgs.py", "reset_organization"),
    ("orgs.py", "delete_organization"),
    ("credentials.py", "_validate_remote"),
    ("google_oidc.py", "consume"),
}
WORKER_STEPS = {
    ("credentials.py", "record_error"),
    ("anomaly_store.py", "purge_expired"),
    ("budgets.py", "evaluate_budgets"),
    ("projection.py", "run_projection"),
    ("delivery.py", "deliver_all"),
}


def _modules_routes_import() -> set[Path]:
    """`costura` modules imported by a router or by the api package itself."""
    found: set[Path] = set()
    for path in _sources(PACKAGE / "api"):
        for node in ast.walk(ast.parse(path.read_text())):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                if not name.startswith("costura."):
                    continue
                parts = name.split(".")[1:]
                candidate = PACKAGE.joinpath(*parts).with_suffix(".py")
                if candidate.is_file():
                    found.add(candidate)
    return found


def _commits(path: Path) -> list[tuple[str, int]]:
    """`(enclosing function, line)` for every `.commit()` call in a module."""
    tree = ast.parse(path.read_text())
    commits: list[tuple[str, int]] = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "commit"
            ):
                commits.append((function.name, node.lineno))
    return commits


WORKER_SIDE = {"scheduler.py", "sync_cycle.py", "scheduler_lock.py", "deps.py"}


def test_request_path_domain_modules_do_not_commit() -> None:
    """`get_session` commits once per request; a module a route imports adds no commit of its
    own. `REQUEST_PATH_COMMITS` must land before something the request cannot undo: a reset
    or delete commits before the organization's advisory lock is released, a rejected key
    keeps its error and a spent OIDC state stays spent when the request then fails.
    `WORKER_STEPS` live in modules routes import but only the worker calls them."""
    modules = {
        path
        for path in _modules_routes_import()
        if ROUTERS not in path.parents and path.name not in WORKER_SIDE
    }
    assert {path.name for path in modules} >= {"accounts.py", "auth.py", "members.py"}
    offenders = sorted(
        f"{path.relative_to(PACKAGE)}:{line} in {function}"
        for path in modules
        for function, line in _commits(path)
        if (path.name, function) not in REQUEST_PATH_COMMITS | WORKER_STEPS
    )
    assert offenders == []


def test_routes_never_call_a_worker_step() -> None:
    names = {function for _, function in WORKER_STEPS}
    offenders = [
        f"{path.relative_to(PACKAGE)}:{number}"
        for path in _sources(PACKAGE / "api")
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if any(re.search(rf"\b{name}\b", line) for name in names)
    ]
    assert offenders == []


CONNECTORS = ("anthropic", "openai", "openrouter", "cursor", "copilot", "claude_ai", "codex")


def test_only_provider_packages_compare_provider_names() -> None:
    """Billing rules read a `ProviderSpec` flag; a name comparison elsewhere hides a
    capability the next connector would have to find by search. Any literal connector name
    compared with `==`, `!=` or `in`, or bound to a module constant, counts. The provider
    packages and the sample organization (`costura/demo`, which builds every connector's
    fixtures) are exempt."""
    names = "|".join(CONNECTORS)
    literal = rf"""["']({names})["']"""
    patterns = (
        re.compile(rf"[!=]=\s*{literal}"),
        re.compile(rf"{literal}\s*[!=]="),
        re.compile(rf"\bin\s*[(\[{{][^)\]}}]*{literal}"),
        re.compile(rf"^[A-Z_]+\s*=\s*{literal}"),
    )
    offenders = [
        f"{path.relative_to(PACKAGE)}:{number}"
        for path in _sources(PACKAGE)
        if not {"providers", "demo"} & set(path.relative_to(PACKAGE).parts)
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if any(pattern.search(line) for pattern in patterns)
    ]
    assert offenders == []


FOUNDATION = {"config", "db", "errors", "secrets", "telemetry"}
LAYERS: dict[str, set[str]] = {
    "models": {"models"},
    "spend": {"spend", "providers", "models"},
    "providers": {"spend", "providers", "models"},
}
ROUTER_SIDE = {"routers", "deps", "guard", "ratelimit", "access"}


def _costura_imports(path: Path) -> list[tuple[int, str]]:
    """`(line, dotted module)` for every `costura.*` import in a module."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
    return [(line, name) for line, name in found if name.startswith("costura.")]


def test_rules_and_tables_import_downward_only() -> None:
    """The layering reads top to bottom: `models` imports only tables, `spend` and `providers`
    import rules, connectors and tables. A service module (`costura/*.py`), a presenter or a
    router above them is out of reach, so a rule never depends on the HTTP layer or on the
    orchestration that calls it. `FOUNDATION` modules carry settings, the engine and the
    error base and are shared by every layer."""
    offenders = sorted(
        f"{path.relative_to(PACKAGE)}:{line} imports {name}"
        for layer, allowed in LAYERS.items()
        for path in _sources(PACKAGE / layer)
        for line, name in _costura_imports(path)
        if name.split(".")[1] not in allowed | FOUNDATION
    )
    assert offenders == []


def test_presenters_and_schemas_stay_below_the_routers() -> None:
    """A presenter shapes a response for any caller (the worker's webhook delivery reuses
    them); one that imports a router or a request dependency can only run under HTTP."""
    offenders = sorted(
        f"{path.relative_to(PACKAGE)}:{line} imports {name}"
        for layer in ("presenters", "schemas")
        for path in _sources(PACKAGE / "api" / layer)
        for line, name in _costura_imports(path)
        if name.startswith("costura.api.") and name.split(".")[2] in ROUTER_SIDE
    )
    assert offenders == []
