"""Request ids, JSON logs and the Prometheus text endpoint."""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import __version__
from costura.metrics import http_requests
from costura.models import ProviderSyncRun, SchedulerRun, SpendAnomaly
from costura.ops.heartbeat import beat
from costura.telemetry import JsonFormatter, request_id_var, resolve_request_id
from tests.conftest import ORG_ID


def test_request_id_accepts_a_token_and_replaces_anything_else() -> None:
    assert resolve_request_id("trace-1") == "trace-1"
    minted = resolve_request_id("bad id")
    assert minted != "bad id"
    assert re.fullmatch(r"[a-f0-9]{32}", minted)
    assert re.fullmatch(r"[a-f0-9]{32}", resolve_request_id("line\nbreak"))


def test_json_formatter_adds_the_request_id() -> None:
    record = logging.LogRecord("costura.access", logging.INFO, __file__, 1, "hello", (), None)
    token = request_id_var.set("trace-1")
    try:
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert payload["message"] == "hello"
    assert payload["request_id"] == "trace-1"
    assert payload["logger"] == "costura.access"
    bare = json.loads(JsonFormatter().format(record))
    assert "request_id" not in bare


def test_json_formatter_carries_the_sync_step_fields() -> None:
    record = logging.LogRecord("costura.sync", logging.INFO, __file__, 1, "sync step", (), None)
    record.__dict__.update(run_id=7, provider="openai", step="cost", duration_seconds=1.25)
    payload = json.loads(JsonFormatter().format(record))
    assert (payload["run_id"], payload["provider"], payload["step"]) == (7, "openai", "cost")
    assert payload["duration_seconds"] == 1.25
    assert "month" not in payload


def test_health_echoes_a_request_id(client: TestClient) -> None:
    echoed = client.get("/health", headers={"X-Request-ID": "trace-1"})
    assert echoed.status_code == 200
    assert echoed.headers["x-request-id"] == "trace-1"
    replaced = client.get("/health", headers={"X-Request-ID": "not a token"})
    assert re.fullmatch(r"[a-f0-9]{32}", replaced.headers["x-request-id"])


def test_metrics_reports_http_and_queue_depth(client: TestClient, db_session: Session) -> None:
    http_requests.reset()
    db_session.add(
        SchedulerRun(
            organization_id=ORG_ID,
            provider="anthropic",
            trigger="manual",
            status="queued",
        )
    )
    db_session.commit()
    assert client.get("/live").status_code == 200
    body = client.get("/metrics").text
    assert body.endswith("\n")
    assert 'costura_http_requests_total{method="GET",route="/live",status="200"} 1' in body
    assert 'costura_http_request_duration_seconds_count{method="GET",route="/live"} 1' in body
    assert (
        'costura_http_request_duration_seconds_bucket{method="GET",route="/live",le="+Inf"} 1'
        in (body)
    )
    assert 'costura_scheduler_queue_depth{status="queued"} 1' in body
    assert 'costura_scheduler_queue_depth{status="running"} 0' in body
    assert "costura_provider_sync_runs" in body
    assert 'costura_webhook_deliveries{status="failed"} 0' in body
    assert f'costura_build_info{{version="{__version__}"}} 1' in body
    assert "costura_metrics_db_up 1" in body


def test_metrics_collapse_unrouted_paths(client: TestClient, db_session: Session) -> None:
    """A probe of random URLs adds one series, not one per path."""
    http_requests.reset()
    for path in ("/nope-1", "/nope-2"):
        assert client.get(path).status_code == 404
    body = client.get("/metrics").text
    assert 'costura_http_requests_total{method="GET",route="unmatched",status="404"} 2' in body
    assert "/nope-1" not in body


def test_the_example_alerts_use_only_exported_metrics(client: TestClient) -> None:
    rules = (Path(__file__).resolve().parents[3] / "examples/prometheus/alerts.yml").read_text()
    used = set(re.findall(r"\bcostura_[a-z_]+", rules))
    exported = set(re.findall(r"^# TYPE (\S+)", client.get("/metrics").text, flags=re.M))
    assert used and used <= exported


def test_metrics_label_routes_without_the_api_prefix(client: TestClient) -> None:
    """The `route` label is the router's template; docs/operations/monitoring.md says so."""
    http_requests.reset()
    assert client.get("/api/v1/orgs").status_code == 200
    body = client.get("/metrics").text
    assert 'costura_http_requests_total{method="GET",route="/orgs",status="200"} 1' in body


def test_detection_lag_counts_hours_after_the_anomaly_day(db_session: Session) -> None:
    from datetime import UTC, date, datetime, timedelta

    from costura.metrics import _detection_lag
    from costura.spend.anomalies import run_detection
    from costura.spend.window import Window
    from tests.conftest import ORG_ID
    from tests.seed import seed_days
    from tests.test_anomalies import HISTORY_START, SPIKE_DAY, spiked

    seed_days(db_session, ORG_ID, "anthropic", HISTORY_START, date(2026, 8, 21), spiked)
    run_detection(db_session, ORG_ID, "anthropic", Window.for_month("2026-08"))
    detected = datetime(SPIKE_DAY.year, SPIKE_DAY.month, SPIKE_DAY.day, tzinfo=UTC)
    for row in db_session.scalars(select(SpendAnomaly)):
        row.detected_at = detected + timedelta(days=2, hours=6)
    db_session.commit()

    count, total = _detection_lag(db_session, now=detected + timedelta(days=5))
    assert count == 2 and total == 2 * 30.0


def test_metrics_export_heartbeats_and_the_last_success_per_provider(
    client: TestClient, db_session: Session
) -> None:
    finished = datetime(2026, 10, 1, 6, 30, tzinfo=UTC)
    for status, at in (("succeeded", finished), ("failed", finished + timedelta(hours=1))):
        db_session.add(
            ProviderSyncRun(
                organization_id=ORG_ID,
                provider="anthropic",
                endpoint="cost_report",
                window_start=finished - timedelta(days=1),
                window_end=finished,
                started_at=at - timedelta(minutes=1),
                finished_at=at,
                status=status,
            )
        )
    db_session.commit()
    beat("scheduler", owner="scheduler-test")

    body = client.get("/metrics").text
    assert (
        'costura_provider_last_success_timestamp_seconds{org="default",provider="anthropic"} '
        f"{int(finished.timestamp())}"
    ) in body
    assert "\ncostura_scheduler_last_seen_seconds " in body
    assert client.get("/health").json()["version"] == __version__
