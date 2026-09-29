from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # ON DELETE CASCADE needs this on SQLite
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure_engine(url: str) -> None:
    """Rebind the global engine (used by tests)."""
    global engine
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns() -> None:
    """Lightweight forward migration: add columns that newer code expects to an
    existing database (new columns are all nullable or defaulted). IMPLEMENTATION
    DECISION: stands in for Alembic while the schema is still moving."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))
                    have.add(col.name)
                # Backfill existing rows with the column's scalar default (e.g. is_demo=False),
                # so older rows never carry NULL where the code expects a value.
                default = getattr(col.default, "arg", None)
                if col.name in have and isinstance(default, (bool, int, float, str)):
                    conn.execute(text(f'UPDATE "{table.name}" SET "{col.name}" = :v WHERE "{col.name}" IS NULL'), {"v": default})


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)
    from app.services.reference_seed import load_reference_seeds

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    with SessionLocal() as db:
        load_reference_seeds(db)
        db.commit()
