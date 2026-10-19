"""Symmetric encryption for stored provider credentials and webhook URLs.

Fernet (AES-128-CBC plus HMAC-SHA256, versioned tokens) keyed by `COSTURA_SECRET_KEY`. New
ciphertext always uses that key. During a rotation `COSTURA_SECRET_KEY_PREVIOUS` holds the
old one: reads try the current key, then the previous (`MultiFernet`), so the processes keep
working while `secret-rotate` rewrites the rows. `key_version` on the row leaves room for a
later scheme without a migration.
"""

import hashlib
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from costura.config import Settings

KEY_VERSION = 1


class SecretKeyMissing(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "COSTURA_SECRET_KEY is not set; generate one with `just api::secret-generate` and "
            "add it to the repo-root .env"
        )


class DecryptError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "stored credential cannot be decrypted with the current COSTURA_SECRET_KEY; "
            "reconnect the provider key in the web settings page"
        )


class ContextMismatch(DecryptError):
    """The ciphertext was written for another row: it was copied or moved in the database."""


BOUND_PREFIX = "costura-bound:1:"


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


def _fernet(settings: Settings) -> Fernet:
    if settings.costura_secret_key is None:
        raise SecretKeyMissing()
    try:
        return Fernet(settings.costura_secret_key.get_secret_value().encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "COSTURA_SECRET_KEY is not a valid Fernet key (urlsafe base64, 32 bytes)"
        ) from exc


def _previous(settings: Settings) -> Fernet | None:
    secret = settings.costura_secret_key_previous
    if secret is None or not secret.get_secret_value().strip():
        return None
    return _parse(secret.get_secret_value().strip(), "COSTURA_SECRET_KEY_PREVIOUS")


def _parse(value: str, name: str) -> Fernet:
    try:
        return Fernet(value.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"{name} is not a valid Fernet key (urlsafe base64, 32 bytes)") from exc


def _reader(settings: Settings, *extra: Fernet) -> MultiFernet:
    previous = _previous(settings)
    return MultiFernet([_fernet(settings), *([previous] if previous else []), *extra])


def encrypt(settings: Settings, plaintext: str) -> bytes:
    return _fernet(settings).encrypt(plaintext.encode("utf-8"))


def decrypt(settings: Settings, ciphertext: bytes) -> str:
    try:
        return _reader(settings).decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptError() from exc


def key_of(settings: Settings, ciphertext: bytes) -> Literal["current", "previous"]:
    """Which configured key reads `ciphertext`; DecryptError when neither does."""
    try:
        _fernet(settings).decrypt(ciphertext)
        return "current"
    except InvalidToken:
        pass
    previous = _previous(settings)
    try:
        if previous is not None:
            previous.decrypt(ciphertext)
            return "previous"
    except InvalidToken:
        pass
    raise DecryptError()


def encrypt_bound(settings: Settings, context: str, plaintext: str) -> bytes:
    """Encrypt `plaintext` together with the row it belongs to (`context`, such as
    `credential|<org>|<provider>|<account>`), so the ciphertext only decrypts for that row."""
    return encrypt(settings, f"{BOUND_PREFIX}{context}\n{plaintext}")


def _unbind(context: str, plaintext: str) -> tuple[str, bool]:
    """The value and whether it carried a context. A context for another row raises."""
    if not plaintext.startswith(BOUND_PREFIX):
        return plaintext, False
    bound, _, value = plaintext[len(BOUND_PREFIX) :].partition("\n")
    if bound != context:
        raise ContextMismatch()
    return value, True


def decrypt_bound(settings: Settings, context: str, ciphertext: bytes) -> str:
    """Decrypt a value written by `encrypt_bound` for `context`. A value written before
    binding (no context) still reads until `secret-rotate` rewrites it."""
    value, _ = _unbind(context, decrypt(settings, ciphertext))
    return value


def is_bound(settings: Settings, context: str, ciphertext: bytes) -> bool:
    _, bound = _unbind(context, decrypt(settings, ciphertext))
    return bound


def reencrypt(old_key: str | None, settings: Settings, ciphertext: bytes, context: str) -> bytes:
    """Encrypt with the current key and bind to `context`, whatever key wrote it: the
    current one, the configured previous one, or `old_key`. A row already rewritten is
    rewritten again, so running a rotation twice is harmless; a row bound to another context
    raises ContextMismatch."""
    extra = [] if not old_key else [_parse(old_key, "the previous key")]
    try:
        plaintext = _reader(settings, *extra).decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptError() from exc
    value, _ = _unbind(context, plaintext)
    return encrypt_bound(settings, context, value)


def credential_context(org_id: int, provider: str, account_id: int) -> str:
    return f"credential|{org_id}|{provider}|{account_id}"


def webhook_context(org_id: int, field: str) -> str:
    return f"webhook-{field}|{org_id}"


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a bearer token; only the digest is stored."""
    return hashlib.sha256(token.encode()).hexdigest()
