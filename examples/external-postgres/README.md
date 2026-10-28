# External PostgreSQL

Run the production Compose stack against a managed PostgreSQL instead of the bundled
`postgres` service. The procedure and the requirements are in
[docs/operations/install.md](../../docs/operations/install.md#a-managed-postgresql-instead-of-the-bundled-one);
this folder holds the override file that guide asks for.

`docker-compose.external-postgres.yml` mounts the provider's CA bundle read-only at
`/run/costura/db-ca.crt` in the `migrate`, `api`, `worker` and `scheduler` services, the path
the example `COSTURA_DATABASE_OPTIONS` in `.env.example` names. It changes nothing else: the
database URLs already read `COSTURA_DATABASE_HOST`, `COSTURA_DATABASE_PORT` and
`COSTURA_DATABASE_OPTIONS` from `.env`.

## Run

In the production `.env` (see `.env.example`):

```sh
COSTURA_DATABASE_HOST=db.example.internal
COSTURA_DATABASE_PORT=5432
COSTURA_DATABASE_OPTIONS=sslmode=verify-full&sslrootcert=/run/costura/db-ca.crt
COSTURA_DATABASE_CA=/etc/costura/db-ca.crt
```

`COSTURA_DATABASE_CA` is the path on the host; it is read by this override only.
`POSTGRES_USER` and `POSTGRES_PASSWORD` are the schema owner on the managed server, which must
be able to create and alter roles; `POSTGRES_APP_USER` and `POSTGRES_APP_PASSWORD` are the
runtime role the migration creates. Then:

```sh
COSTURA_COMPOSE="docker compose -f docker-compose.prod.yml -f examples/external-postgres/docker-compose.external-postgres.yml" \
  just prod::up
```

`COSTURA_COMPOSE` points every `just prod::*` recipe at the two files. The same prefix works
with `prod::down`, `prod::logs` and `prod::ps`. The bundled `postgres` service still starts
and stays empty. `just prod::backup` and `prod::restore` reach only that service, so they
refuse to run while `COSTURA_DATABASE_HOST` names another server, and `just prod::upgrade`
takes no backup; back up the managed database with the provider's tools.

Check the merged file before the first start:

```sh
docker compose -f docker-compose.prod.yml -f examples/external-postgres/docker-compose.external-postgres.yml config --quiet
```
