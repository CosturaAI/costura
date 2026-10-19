from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from costura.config import get_settings

# Deterministic constraint names so Alembic autogenerate emits stable, droppable names.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@lru_cache
def get_engine() -> Engine:
    """The process engine, built on first use so importing a module never reads settings."""
    return create_engine(get_settings().database_url, pool_pre_ping=True)


class _EngineSession(Session):
    def __init__(self, bind: Any = None, **kwargs: Any) -> None:
        super().__init__(bind=bind if bind is not None else get_engine(), **kwargs)


SessionLocal = sessionmaker(class_=_EngineSession, autoflush=False, expire_on_commit=False)
