"""Encryption key operations: `python -m costura.ops.secret generate|rotate|check`.

`generate` prints a new COSTURA_SECRET_KEY. `rotate` reads rows with the current key,
COSTURA_SECRET_KEY_PREVIOUS or a key on stdin, and re-encrypts every stored provider
credential and webhook destination under the current key, bound to its row, in one
transaction; any row that fails to decrypt aborts the whole rotation, and a second run
changes nothing a reader can tell. `check` decrypts every stored credential and webhook
destination, counts them per key and the rows not yet bound, and exits non-zero when one
fails. It prints counts, never plaintext.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from costura.config import Settings
from costura.ops import OperationError, run


@dataclass(frozen=True)
class Rotation:
    credentials: int
    webhooks: int = 0


def rotate(session: Session, settings: Settings, old_key: str | None) -> Rotation:
    """Re-encrypt every stored credential and webhook destination under the current key,
    reading with the current key, `COSTURA_SECRET_KEY_PREVIOUS` or `old_key`; commit all or
    none. A row already on the current key is rewritten as well, so a second run is a no-op
    in effect."""
    from costura.models.credential import ProviderCredential
    from costura.models.delivery import WebhookDestination
    from costura.secrets import (
        KEY_VERSION,
        DecryptError,
        SecretKeyMissing,
        credential_context,
        reencrypt,
        webhook_context,
    )

    rows = session.query(ProviderCredential).order_by(ProviderCredential.id).all()
    hooks = session.query(WebhookDestination).order_by(WebhookDestination.organization_id).all()
    try:
        for row in rows:
            context = credential_context(row.organization_id, row.provider, row.account_id)
            row.ciphertext = reencrypt(old_key, settings, row.ciphertext, context)
            row.key_version = KEY_VERSION
        for hook in hooks:
            org_id = hook.organization_id
            hook.url_ciphertext = reencrypt(
                old_key, settings, hook.url_ciphertext, webhook_context(org_id, "url")
            )
            hook.secret_ciphertext = reencrypt(
                old_key, settings, hook.secret_ciphertext, webhook_context(org_id, "secret")
            )
            hook.key_version = KEY_VERSION
    except (DecryptError, SecretKeyMissing, RuntimeError) as exc:
        session.rollback()
        raise OperationError(f"rotation aborted, nothing changed: {exc}") from exc
    session.commit()
    return Rotation(credentials=len(rows), webhooks=len(hooks))


@dataclass(frozen=True)
class Check:
    current: int
    previous: int
    unbound: int = 0

    @property
    def total(self) -> int:
        return self.current + self.previous


def check(session: Session, settings: Settings) -> Check:
    """Decrypt every stored credential and webhook destination and count them per key. Raise
    when any row fails."""
    from costura.models.credential import ProviderCredential
    from costura.models.delivery import WebhookDestination
    from costura.secrets import (
        DecryptError,
        SecretKeyMissing,
        credential_context,
        is_bound,
        key_of,
        webhook_context,
    )

    blobs = [
        (credential_context(row.organization_id, row.provider, row.account_id), row.ciphertext)
        for row in session.query(ProviderCredential)
    ]
    for hook in session.query(WebhookDestination):
        blobs += [
            (webhook_context(hook.organization_id, "url"), hook.url_ciphertext),
            (webhook_context(hook.organization_id, "secret"), hook.secret_ciphertext),
        ]
    counts = {"current": 0, "previous": 0}
    unbound = 0
    failed = 0
    for context, blob in blobs:
        try:
            counts[key_of(settings, blob)] += 1
            unbound += not is_bound(settings, context, blob)
        except (DecryptError, SecretKeyMissing, RuntimeError) as exc:
            del exc
            failed += 1
    if failed:
        raise OperationError(
            f"{failed} of {len(blobs)} stored secret(s) did not decrypt for their row"
        )
    return Check(current=counts["current"], previous=counts["previous"], unbound=unbound)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.secret", description=__doc__)
    parser.add_argument("action", choices=("generate", "rotate", "check"))
    args = parser.parse_args(argv)

    def operation() -> int:
        if args.action == "generate":
            from costura.secrets import generate_key

            print(generate_key())
            return 0
        from costura.config import get_settings
        from costura.db import SessionLocal

        if args.action == "check":
            with SessionLocal() as session:
                counted = check(session, get_settings())
            print(
                f"decrypted {counted.total} stored secret(s): {counted.current} with "
                f"COSTURA_SECRET_KEY, {counted.previous} with COSTURA_SECRET_KEY_PREVIOUS, "
                f"{counted.unbound} not yet bound to their row (run secret-rotate)"
            )
            return 0

        settings = get_settings()
        old_key = "" if sys.stdin.isatty() else sys.stdin.read().strip()
        with SessionLocal() as session:
            result = rotate(session, settings, old_key or None)
        print(
            f"re-encrypted {result.credentials} credential(s) and {result.webhooks} webhook "
            "destination(s) with the current COSTURA_SECRET_KEY"
        )
        return 0

    return run(operation)


if __name__ == "__main__":
    sys.exit(main())
