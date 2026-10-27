"""数据库引擎。SQLite 打开外键；内存库使用 StaticPool，避免每个连接一份空库。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.settings import get_settings


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _ensure_sqlite_parent(url: str) -> None:
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url.startswith("sqlite:////"):
        return
    relative = url.removeprefix(prefix)
    if relative in {":memory:", ""}:
        return
    Path(relative).parent.mkdir(parents=True, exist_ok=True)


def make_engine(url: str | None = None) -> Engine:
    db_url = get_settings().database_url if url is None else url
    options: dict[str, Any] = {}
    if db_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if db_url in {"sqlite://", "sqlite:///:memory:"}:
            options["poolclass"] = StaticPool
        else:
            _ensure_sqlite_parent(db_url)
    engine = create_engine(db_url, **options)
    if db_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
