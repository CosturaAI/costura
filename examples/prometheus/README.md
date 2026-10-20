# Prometheus alerts

[`alerts.yml`](alerts.yml) turns the alert starting points in
[monitoring](../../docs/operations/monitoring.md#metrics) into Prometheus rules for one
install. It assumes the scrape job is named `costura` and reaches `api:8000` on the
`costura-prod_default` network:

```yaml
rule_files: [alerts.yml]
scrape_configs:
  - job_name: costura
    static_configs:
      - targets: ["api:8000"]
```

`severity: page` needs someone now (API, database, worker or scheduler down);
`severity: ticket` can wait for working hours (mixed releases after an upgrade, a stuck
queue, a failed sync, a provider silent for 36 hours, a failed webhook, sustained 429s). Route them in Alertmanager.

Check the file with the Prometheus image's `promtool` before loading it:

```
docker run --rm --entrypoint promtool -v "$PWD/examples/prometheus:/rules:ro" \
  prom/prometheus:v3.15.0@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e \
  check rules /rules/alerts.yml
```

`apps/api/tests/test_observe.py` fails when a rule names a metric `/metrics` does not export.
