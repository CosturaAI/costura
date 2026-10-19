# Examples

Small, runnable complements to the operations guides. Each folder is documentation with
files; none is part of the release, the test suites or the images.

| Folder                                             | Shows                                                                                            | Run                                                                                                                   |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| [external-postgres](external-postgres/README.md)   | The Compose override that mounts a CA bundle so the stack reaches a managed PostgreSQL over TLS | `COSTURA_COMPOSE="docker compose -f docker-compose.prod.yml -f examples/external-postgres/docker-compose.external-postgres.yml" just prod::up` |
| [slack-webhook-receiver](slack-webhook-receiver/README.md) | A 40-line Python receiver that verifies `X-Costura-Signature` and prints each signal        | `COSTURA_WEBHOOK_SECRET=... python3 -I examples/slack-webhook-receiver/receiver.py 8089`                              |
