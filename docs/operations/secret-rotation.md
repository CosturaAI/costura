# Secret rotation

Every production secret lives in `.env` next to `docker-compose.prod.yml`. Rotate one on a
schedule or after an exposure; [SECURITY.md](../../SECURITY.md) has the incident order (revoke
at the provider first, then rotate here). `just prod::up` re-creates each service whose
variables changed, so it is the restart step below.

| Secret | Rotate with | Restarts |
| --- | --- | --- |
| `COSTURA_SECRET_KEY` | the rotation below and `just prod::secret-rotate` | api, worker, scheduler |
| `POSTGRES_APP_PASSWORD` | a new value in `.env`, then `just prod::up` | migrate, api, worker, scheduler |
| `POSTGRES_PASSWORD` | `\password` in psql, then the same value in `.env` and `just prod::up` | migrate |
| `COSTURA_OPERATOR_SECRET` | a new value of at least 24 characters, then `just prod::up` | api |
| `GOOGLE_CLIENT_SECRET` | a new secret in the Google console, then `.env` and `just prod::up` | api |
| A provider admin key | the provider's console, then Settings, Connections | none |
| A webhook URL and its signing secret | a new URL in Settings, Anomalies | none |

## `COSTURA_SECRET_KEY`

Stored provider keys and webhook URLs are encrypted with it. The API, the worker and the
scheduler accept two keys during a rotation, so nothing stops reading.

1. Take a backup (`just prod::backup <file>`). A dump made before the rotation needs the
   old key to be read; keep that key with the dumps that need it.
2. Move the current value to `COSTURA_SECRET_KEY_PREVIOUS` and put a new one in
   `COSTURA_SECRET_KEY` (`openssl rand -base64 32 | tr '+/' '-_'`). Run `just prod::up`.
3. Run `just prod::secret-rotate`. It re-encrypts every row under the new key, or none.
4. Run `just prod::secret-check`. When it reports 0 rows with `COSTURA_SECRET_KEY_PREVIOUS`,
   remove that variable and run `just prod::up` again.

## `POSTGRES_APP_PASSWORD`

The runtime role's password is set by every migration, and `just prod::up` runs the
migration before it starts the API, the worker and the scheduler. Put a new value of at
least 12 characters (`openssl rand -hex 16`) in `.env`, different from `POSTGRES_PASSWORD`,
and run `just prod::up`.

## `POSTGRES_PASSWORD`

The schema owner's password is set once, when the database volume is created; `.env` alone
does not change it. Change it in the database, then in `.env`:

```
docker compose -f docker-compose.prod.yml exec postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\password $POSTGRES_USER"'
```

Type the new value twice at the prompt, so it stays out of the shell history. Put the same
value in `POSTGRES_PASSWORD` and run `just prod::up`; the migration connects with it.

## `COSTURA_OPERATOR_SECRET` and `GOOGLE_CLIENT_SECRET`

Replace the value in `.env` and run `just prod::up`. A session opened with the old operator
secret stays valid until it is revoked: `DELETE /api/v1/auth/sessions` as that user, or
delete that user's rows in `sessions`. Once an owner signs in with Google, remove the operator
pair instead of rotating it ([install](install.md)).

## Provider keys and webhook URLs

Revoke the key in the provider's console, then replace it in Settings, Connections, on the
account row; the audit trail records who replaced it. A webhook URL is revoked in the chat
tool; saving the new URL in Settings, Anomalies also issues a new signing secret. A key in
`.env` (the `COSTURA_ORG` fallback) is replaced there, followed by `just prod::up`.
