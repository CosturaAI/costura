"""In-process HTTP counters and latency histograms plus database gauges, rendered as
Prometheus text.

HTTP totals live in this process and reset when it exits. Queue depth and sync
counts are read from PostgreSQL at scrape time, so the API and the worker share them.
`GET /metrics` is not part of the OpenAPI contract; keep it on a private network.
"""

import logging
import re
import threading
from datetime import UTC, datetime, timedelta

from fastapi.responses import PlainTextResponse
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from costura import __version__
from costura.db import SessionLocal
from costura.models import ProviderSyncRun, SchedulerRun, SpendAnomaly, WebhookDelivery
from costura.models.delivery import DELIVERY_STATUSES
from costura.models.heartbeat import HEARTBEAT_ROLES, WorkerHeartbeat
from costura.models.organization import Organization
from costura.ops.purge import COMPLETED_SYNC_STATUSES, TERMINAL_SCHEDULER_STATUSES

LAG_WINDOW_DAYS = 30

log = logging.getLogger("costura.metrics")

_METHOD = re.compile(r"^[A-Z]{1,16}$")


# Upper bounds in seconds; a request slower than the last lands only in `+Inf`.
LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class HttpCounter:
    """Request totals keyed by method, route template and status, and a latency histogram
    keyed by method and route. One lock; routes are templates, so the maps stay small."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str, str], int] = {}
        self._latency: dict[tuple[str, str], list[float]] = {}

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        verb = _safe_method(method)
        with self._lock:
            key = (verb, route, str(status))
            self._values[key] = self._values.get(key, 0) + 1
            # Per bucket counts, then the sum and the count of every observation.
            series = self._latency.setdefault((verb, route), [0.0] * (len(LATENCY_BUCKETS) + 2))
            for index, bound in enumerate(LATENCY_BUCKETS):
                if seconds <= bound:
                    series[index] += 1
            series[-2] += seconds
            series[-1] += 1

    def snapshot(self) -> list[tuple[tuple[str, str, str], int]]:
        with self._lock:
            return sorted(self._values.items())

    def latency(self) -> list[tuple[tuple[str, str], list[float]]]:
        with self._lock:
            return sorted((key, list(series)) for key, series in self._latency.items())

    def reset(self) -> None:
        with self._lock:
            self._values.clear()
            self._latency.clear()


def _safe_method(method: str) -> str:
    text = method.upper()
    return text if _METHOD.fullmatch(text) else "OTHER"


http_requests = HttpCounter()


def _line(name: str, labels: dict[str, str], value: float | int | str) -> str:
    if not labels:
        rendered = f"{name} {value}"
    else:
        body = ",".join(f'{key}="{label}"' for key, label in labels.items())
        rendered = f"{name}{{{body}}} {value}"
    return rendered


def _grouped(session: Session, model, statuses: tuple[str, ...]) -> dict[str, int]:
    counts = dict.fromkeys(statuses, 0)
    rows = session.execute(
        select(model.status, func.count()).where(model.status.in_(statuses)).group_by(model.status)
    ).all()
    for status, count in rows:
        if status in counts:
            counts[str(status)] = int(count)
    return counts


def _duration(session: Session) -> dict[str, tuple[int, float]]:
    epoch = extract("epoch", SchedulerRun.finished_at - SchedulerRun.started_at)
    rows = session.execute(
        select(SchedulerRun.status, func.count(), func.coalesce(func.sum(epoch), 0.0))
        .where(
            SchedulerRun.status.in_(TERMINAL_SCHEDULER_STATUSES),
            SchedulerRun.finished_at.is_not(None),
        )
        .group_by(SchedulerRun.status)
    ).all()
    found = {status: (int(count), float(total)) for status, count, total in rows}
    return {status: found.get(status, (0, 0.0)) for status in TERMINAL_SCHEDULER_STATUSES}


def database_samples(session: Session) -> list[str]:
    """Gauges a scraper can read without sharing memory with the worker."""
    lines = [
        "# HELP costura_scheduler_queue_depth Scheduler rows waiting or in progress",
        "# TYPE costura_scheduler_queue_depth gauge",
    ]
    queue = _grouped(session, SchedulerRun, ("queued", "running"))
    for status, count in queue.items():
        lines.append(_line("costura_scheduler_queue_depth", {"status": status}, count))
    lines += [
        "# HELP costura_scheduler_runs Scheduler rows by terminal or active status",
        "# TYPE costura_scheduler_runs gauge",
    ]
    runs = _grouped(session, SchedulerRun, ("queued", "running", *TERMINAL_SCHEDULER_STATUSES))
    for status, count in runs.items():
        lines.append(_line("costura_scheduler_runs", {"status": status}, count))
    lines += [
        "# HELP costura_scheduler_duration_seconds_sum Sum of finished scheduler durations",
        "# TYPE costura_scheduler_duration_seconds_sum gauge",
        "# HELP costura_scheduler_duration_seconds_count Finished scheduler runs with a duration",
        "# TYPE costura_scheduler_duration_seconds_count gauge",
    ]
    for status, (count, total) in _duration(session).items():
        lines.append(_line("costura_scheduler_duration_seconds_count", {"status": status}, count))
        lines.append(
            _line("costura_scheduler_duration_seconds_sum", {"status": status}, f"{total:.3f}")
        )
    lines += [
        "# HELP costura_provider_sync_runs Provider sync runs by status",
        "# TYPE costura_provider_sync_runs gauge",
    ]
    syncs = _grouped(session, ProviderSyncRun, ("running", *COMPLETED_SYNC_STATUSES))
    for status, count in syncs.items():
        lines.append(_line("costura_provider_sync_runs", {"status": status}, count))
    for role in HEARTBEAT_ROLES:
        seen = session.scalar(
            select(func.max(WorkerHeartbeat.last_seen_at)).where(WorkerHeartbeat.role == role)
        )
        lines += [
            f"# HELP costura_{role}_last_seen_seconds Unix time of the newest {role} heartbeat",
            f"# TYPE costura_{role}_last_seen_seconds gauge",
        ]
        if seen is not None:
            lines.append(_line(f"costura_{role}_last_seen_seconds", {}, int(seen.timestamp())))
    lines += [
        "# HELP costura_provider_last_success_timestamp_seconds Unix time the newest succeeded"
        " sync of an organization's provider finished",
        "# TYPE costura_provider_last_success_timestamp_seconds gauge",
    ]
    succeeded = session.execute(
        select(Organization.slug, ProviderSyncRun.provider, func.max(ProviderSyncRun.finished_at))
        .join(Organization, Organization.id == ProviderSyncRun.organization_id)
        .where(ProviderSyncRun.status == "succeeded", ProviderSyncRun.finished_at.is_not(None))
        .group_by(Organization.slug, ProviderSyncRun.provider)
        .order_by(Organization.slug, ProviderSyncRun.provider)
    ).all()
    for slug, provider, finished in succeeded:
        if finished is None:
            continue
        lines.append(
            _line(
                "costura_provider_last_success_timestamp_seconds",
                {"org": slug, "provider": provider},
                int(finished.timestamp()),
            )
        )
    count, total = _detection_lag(session)
    lines += [
        "# HELP costura_anomaly_detection_lag_hours_sum Hours from the end of an anomaly day to"
        " its detection, summed over the anomalies detected in the last 30 days",
        "# TYPE costura_anomaly_detection_lag_hours_sum gauge",
        "# HELP costura_anomaly_detection_lag_hours_count Anomalies detected in the last 30 days",
        "# TYPE costura_anomaly_detection_lag_hours_count gauge",
        _line("costura_anomaly_detection_lag_hours_count", {}, count),
        _line("costura_anomaly_detection_lag_hours_sum", {}, f"{total:.3f}"),
        "# HELP costura_webhook_deliveries Webhook delivery rows by status",
        "# TYPE costura_webhook_deliveries gauge",
    ]
    for status, count in _grouped(session, WebhookDelivery, DELIVERY_STATUSES).items():
        lines.append(_line("costura_webhook_deliveries", {"status": status}, count))
    return lines


def _detection_lag(session: Session, now: datetime | None = None) -> tuple[int, float]:
    moment = now or datetime.now(UTC)
    rows = session.execute(
        select(SpendAnomaly.day, SpendAnomaly.detected_at).where(
            SpendAnomaly.detected_at >= moment - timedelta(days=LAG_WINDOW_DAYS)
        )
    ).all()
    total = 0.0
    for day, detected_at in rows:
        day_end = datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)
        total += max(0.0, (detected_at - day_end).total_seconds() / 3600)
    return len(rows), total


def render_metrics() -> str:
    """Prometheus text exposition. Database failure still returns the HTTP counters."""
    lines = [
        "# HELP costura_build_info The API release this process runs",
        "# TYPE costura_build_info gauge",
        _line("costura_build_info", {"version": __version__}, 1),
        "# HELP costura_http_requests_total HTTP responses from this process",
        "# TYPE costura_http_requests_total counter",
    ]
    for (method, route, status), count in http_requests.snapshot():
        labels = {"method": method, "route": route, "status": status}
        lines.append(_line("costura_http_requests_total", labels, count))
    lines += [
        "# HELP costura_http_request_duration_seconds HTTP response time in this process",
        "# TYPE costura_http_request_duration_seconds histogram",
    ]
    for (method, route), series in http_requests.latency():
        labels = {"method": method, "route": route}
        for bound, count in zip(LATENCY_BUCKETS, series, strict=False):
            bucket = {**labels, "le": str(bound)}
            lines.append(_line("costura_http_request_duration_seconds_bucket", bucket, int(count)))
        total = {**labels, "le": "+Inf"}
        lines.append(_line("costura_http_request_duration_seconds_bucket", total, int(series[-1])))
        lines.append(
            _line("costura_http_request_duration_seconds_sum", labels, f"{series[-2]:.6f}")
        )
        lines.append(_line("costura_http_request_duration_seconds_count", labels, int(series[-1])))
    try:
        with SessionLocal() as session:
            lines.extend(database_samples(session))
        lines.append("# HELP costura_metrics_db_up 1 when the gauge queries succeeded")
        lines.append("# TYPE costura_metrics_db_up gauge")
        lines.append("costura_metrics_db_up 1")
    except Exception as exc:
        log.warning("metrics database read failed: %s", exc)
        lines.append("# HELP costura_metrics_db_up 1 when the gauge queries succeeded")
        lines.append("# TYPE costura_metrics_db_up gauge")
        lines.append("costura_metrics_db_up 0")
    return "\n".join(lines) + "\n"


def metrics_response() -> PlainTextResponse:
    return PlainTextResponse(
        render_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )
