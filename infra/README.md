# infra

Local infrastructure files consumed by `docker-compose.yml` (development Postgres only).

- `postgres/init/`: SQL run by the PostgreSQL image on the first start of an empty data volume.
  `01-test-db.sql` creates `costura_test`. `just api::test` uses its URL as a template and
  creates and drops one `costura_test_<pid>` database per test process.

Production does not use this directory: see [install](../docs/operations/install.md).
