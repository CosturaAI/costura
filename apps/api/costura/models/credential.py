"""Provider credentials stored per organization, encrypted at rest.

`ciphertext` is a Fernet token (see costura.secrets); `key_hint` is the last four characters of
the key, the same fragment the provider Console shows. The plaintext never reaches a column.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base


class ProviderCredential(Base):
    """The admin key of one provider account; one credential per account, and one account per
    key (`key_digest`, sha256 of the plaintext) so the same key is not added twice."""

    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "provider", "key_digest", name="uq_provider_credentials_key_digest"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("provider_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    key_digest: Mapped[str] = mapped_column(Text, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    key_hint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
