# Support

Costura is a self-hosted project. Support is community support through GitHub issues, with
no response-time agreement, uptime target, or hosted instance.

## Where to ask

- Usage questions: [GitHub Discussions](https://github.com/CosturaAI/costura/discussions).
- Bug reports and feature requests: a GitHub issue, with the version (`COSTURA_VERSION` or
  the git tag), `COSTURA_ENV`, and what you expected. Do not paste provider keys, session
  cookies, `COSTURA_SECRET_KEY`, or `.env`.
- How to run it: [Install](docs/operations/install.md),
  [configuration](docs/operations/configuration.md), [upgrade](docs/operations/upgrade.md),
  [backup and restore](docs/operations/backup-restore.md),
  [monitoring](docs/operations/monitoring.md) and
  [troubleshooting](docs/operations/troubleshooting.md).
- A new provider: the "Provider connector" issue form, with the provider's billing API.
- Changes and design questions: [Contributing](CONTRIBUTING.md) and
  [Governance](GOVERNANCE.md).

Security reports do not go in a public issue. Use [SECURITY.md](SECURITY.md). Security
fixes land in the latest release only
([supported versions](SECURITY.md#supported-versions)).

## Language and telemetry

The interface and the documentation are in English only.

Costura sends nothing to its maintainers: no usage statistics, no error reports, no update
check. Next.js telemetry is disabled in the web image (`NEXT_TELEMETRY_DISABLED=1`). The only
outbound calls are the read-only requests to the providers you connect and, when configured,
Google sign-in.

## What you operate

You run the database, the secrets in `.env`, upgrades, and backups. Maintainers do not
have access to your host. A fix lands in this repository; applying it is an upgrade on
your machine.

## What to expect

Maintainers and contributors read issues; there is no response-time commitment. A report
may wait, be closed as out of scope, or be fixed in a later release. Breaking changes
before 1.0 are listed in [CHANGELOG.md](CHANGELOG.md).
