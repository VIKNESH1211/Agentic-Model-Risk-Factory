from __future__ import annotations

from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.domain import tables  # noqa: F401  (register tables)

_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False, "timeout": 30} if _sqlite else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)

if _sqlite:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def drop_all() -> None:
    SQLModel.metadata.drop_all(engine)


@contextmanager
def session():
    with Session(engine, expire_on_commit=False) as s:
        yield s


def save(obj):
    with session() as s:
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return obj
