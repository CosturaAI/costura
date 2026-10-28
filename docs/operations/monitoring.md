# Monitoring

The API exposes probes and Prometheus metrics. Every process writes logs to standard
output. Nothing is sent outside the host. Variables are in [configuration](configuration.md).

## Probes

| Path      | Reaches the database | Through Caddy | Use                                               |
| --------- | -------------------- | ------------- | ------------------------------------------------- |
| `/live`   | no                   | yes           | The API process answers.                          |
| `/ready`  | yes                  | no (404)      | Compose healthcheck of the `api` service.         |
| `/health` | yes                  | no (404)      | `/ready` plus the environment name and `version`. |
| `/metrics`| yes, for the gauges  | no (404)      | Prometheus text, described below.                 |

`deploy/Caddyfile` answers 404 for `/ready`, `/health` and `/metrics`. A scraper reads them
on the Compose network, where the API listens on `api:8000`. Do not publish port 8000.

## Scraping `/metrics`

Attach the scraper to the Compose network of `docker-compose.prod.yml`. The project is
`costura-prod`, so the network is `costura-prod_default`:

```yaml
scrape_configs:
  - job_name: costura
    static_configs:
      - targets: ["api:8000"]
```

For a one-off read from the host:

```sh
docker compose -f docker-compose.prod.yml exec api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode())"
```

## Metrics

HTTP series live in the API process and restart at zero with it. The gauges are read from
PostgreSQL at scrape time, so they include the worker's and the scheduler's work.

| Metric                                    | Type      | Labels                    |
| ----------------------------------------- | --------- | ------------------------- |
| `costura_http_requests_total`             | counter   | `method`, `route`, `status` |
| `costura_http_request_duration_seconds`   | histogram | `method`, `route`         |
| `costura_scheduler_queue_depth`           | gauge     | `status` (`queued`, `running`) |
| `costura_scheduler_runs`                  | gauge     | `status`                  |
| `costura_scheduler_duration_seconds_sum`  | gauge     | `status`                  |
| `costura_scheduler_duration_seconds_count`| gauge     | `status`                  |
| `costura_provider_sync_runs`              | gauge     | `status`                  |
| `costura_worker_last_seen_seconds`        | gauge     | none                      |
| `costura_scheduler_last_seen_seconds`     | gauge     | none                      |
| `costura_provider_last_success_timestamp_seconds` | gauge | `org`, `provider`   |
| `costura_build_info`                      | gauge     | `version`                 |
| `costura_processes`                       | gauge     | `role` (`worker`, `scheduler`), `version` |
| `costura_anomaly_detection_lag_hours_sum` | gauge     | none                      |
| `costura_anomaly_detection_lag_hours_count`| gauge    | none                      |
| `costura_webhook_deliveries`              | gauge     | `status` (`pending`, `sent`, `failed`, `skipped`) |
| `costura_metrics_db_up`                   | gauge     | none                      |

`route` is the route template without the `/api/v1` prefix, such as
`/orgs/{org}/providers/{provider}/months/{month}/usage`; `/live`, `/ready`, `/health` and
`/metrics` keep their own paths.
A path that matches no route is counted as `unmatched`, so scanning random URLs adds one
series. Histogram buckets end at 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5 and 10 seconds.

Starting points for alerts; [`examples/prometheus/alerts.yml`](../../examples/prometheus/alerts.yml)
has them as Prometheus rules:

- `time() - costura_worker_last_seen_seconds > 300`: no worker heartbeat for five minutes.
- `time() - costura_scheduler_last_seen_seconds > 300`: no scheduler heartbeat; the daily
  runs will not be enqueued.
- `time() - costura_provider_last_success_timestamp_seconds > 129600` (36 hours): a provider
  of that organization has not synced since the last daily pass. The Setup page names the
  failed step.
- `count(count by (version) (costura_build_info or costura_processes)) > 1` for 15 minutes:
  the API, the worker and the scheduler run different releases, such as after an upgrade
  that did not restart every service. `costura_build_info` is the API's release (the same
  `version` as `/health`); `costura_processes` counts the worker and scheduler processes with
  a heartbeat in the last five minutes, by release.
- `costura_scheduler_queue_depth{status="queued"} > 0` for an hour: rows wait and no worker claims them.
- `(costura_scheduler_runs{status="failed"} - costura_scheduler_runs{status="failed"} offset 1h) > 0`:
  a sync cycle failed in the last hour. The run's steps are on the Setup page and in the
  worker log. The metric is a row count, a gauge, not a counter: retention deletes old rows
  and lowers it, so `increase()` would read that drop as a counter reset and report a
  failure that did not happen. The difference ignores a drop; a purge in the same hour can
  hide a failure.
- `costura_metrics_db_up == 0`: the API cannot read PostgreSQL.
- `(costura_webhook_deliveries{status="failed"} - costura_webhook_deliveries{status="failed"} offset 1h) > 0`,
  the same row-count gauge: a signal was not posted after five attempts. Settings, Anomalies lists the last error of each delivery and lets an
  owner resend one; the schedule is in [webhooks](webhooks.md).
- `costura_http_requests_total{status="429"}` rising: clients hit `COSTURA_RATE_LIMIT_*`.
  Every limited answer under `/api/v1` carries `RateLimit-Limit`, `RateLimit-Remaining` and
  `RateLimit-Reset` (seconds) for the tightest bucket it fell in, and a 429 carries
  `Retry-After` with the same seconds.

## Logs

Docker keeps each service's output with the `json-file` driver, at most five files of 50 MB
(`x-logging` in `docker-compose.prod.yml`), so the seven services hold up to 1.75 GB and the
oldest lines are dropped first. To keep logs longer or search them centrally, ship them from
the host (a collector reading the Docker log files, or another `logging` driver in a Compose
override).

`COSTURA_LOG_LEVEL` sets the threshold for the `costura` loggers (default `INFO`). In
production each line is one JSON object with `ts`, `level`, `logger` and `message`:

- An HTTP request writes one `costura.access` line with the method, the route template, the
  status and the duration. `request_id` is the incoming `X-Request-ID` when it is a short
  token, otherwise a new id; the response returns it in the same header.
- A sync cycle writes one `costura.sync` line per step, with `run_id`, `org_id`, `provider`,
  `step`, `month`, `status` and `duration_seconds`. A failed step logs at `WARNING`.
- A webhook pass that posted something writes one `costura.worker` line with `sent=`; an
  organization whose pass raised writes a `costura.delivery` line, `webhook delivery failed
  org_id=`, with the traceback.
  Neither line contains the webhook URL.
- The sample warm-up writes one `costura.demo_cache` line each time it renders the pages,
  `demo cache warmed: N of 8 pages`, or `demo cache warm-up failed` at `WARNING` with the
  reason; a failed pass is retried 30 seconds later.

```sh
docker compose -f docker-compose.prod.yml logs worker | grep '"logger": "costura.sync"'
```

Access lines log the route template, so `/people/{email}` does not record the address. A
path that matches no route has any e-mail address replaced with `{email}`.
