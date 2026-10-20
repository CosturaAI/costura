# Security

Costura stores customer provider admin keys (Anthropic Admin API, Claude.ai Enterprise
Analytics, OpenRouter management, OpenAI and Codex admin, Cursor team, and the GitHub token
of the experimental Copilot connector) and the billing and usage data those keys read. It
also stores each organization's signal webhook URL, which lets its holder post to that
channel. A leaked provider key reads a customer's whole spend and
inventory.

## Supported versions

Security fixes land in the latest release. Before 1.0 there is no long-term branch: a fix
ships in the next release, and an operator applies it by upgrading
([upgrade](docs/operations/upgrade.md)).

## Reporting a vulnerability

Do not open a public issue, and do not send a report to a public mailing list. Report
privately with the affected route or file, the steps to reproduce, and the impact you
observed:

1. GitHub private vulnerability reporting (`Security` → `Report a vulnerability`). Only
   maintainers can read the report. There is no e-mail address.

Costura is maintained by volunteers and has no response-time agreement. Maintainers aim to
acknowledge a report within a week, and treat anything that exposes a stored key or another
organization's data before other work. The fix ships in the next release.

## If a credential leaks

Owners see who connected, replaced or removed each key in the audit trail
(`GET /api/v1/orgs/{org}/audit`). Revoke a provider admin key in that provider's console
first. Costura clients are read-only
and cannot revoke it. Then replace the key in Settings, Connections, on the affected account
row, or with `PUT /api/v1/orgs/{org}/providers/{provider}/accounts/{account_id}/key`. If the
leaked key came from `.env`, replace it there and restart the API, the worker and the scheduler.

If `COSTURA_SECRET_KEY` or the database was exposed, move the old key to
`COSTURA_SECRET_KEY_PREVIOUS`, put a new one in `COSTURA_SECRET_KEY`, and restart the API, the
worker and the scheduler; they keep reading every row. Run `just prod::secret-rotate` to
rewrite the rows under the new key, check that `just prod::secret-check` reports none with
`COSTURA_SECRET_KEY_PREVIOUS`, remove that variable and restart again. Then replace every
stored provider key and webhook URL, and delete the affected rows in `sessions`. Discard the old key everywhere it was copied. On a development checkout
the same command is `just api::secret-rotate`.

A leaked webhook URL is revoked in the chat tool (for Slack, remove or regenerate the
incoming webhook); then save the new URL in Settings, Anomalies, which also issues a new
signing secret.

A leaked session is revoked with `DELETE /api/v1/auth/sessions` as that user, or by deleting
that user's rows in `sessions`. Replace a leaked `COSTURA_OPERATOR_SECRET` in `.env` (at least
24 characters), restart the API, and revoke sessions already opened with it. Stop the worker
as well when the database or `COSTURA_SECRET_KEY` was exposed. The trust boundaries and asset
protections are in [docs/security/threat-model.md](docs/security/threat-model.md); the
routine rotation of each secret is in
[docs/operations/secret-rotation.md](docs/operations/secret-rotation.md).
