"""SQLAlchemy 基类与跨库的时区时间类型。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, String
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from src.errors import ConstraintViolation


class Base(DeclarativeBase):
    pass


def enum_col(enum_cls: type[Enum]) -> SAEnum:
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=64,
        values_callable=lambda cls: [member.value for member in cls],
    )


def new_id() -> str:
    from uuid import uuid4

    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AwareDateTime(TypeDecorator[datetime]):
    """写入时拒绝无时区时间。SQLite 读回若丢失时区，按 UTC 还原。

    还原只发生在读路径：绑定参数阶段已经强制转成 UTC。
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ConstraintViolation("datetime", "时间必须带时区", value=value)
        return value.astimezone(timezone.utc)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


ID_COL = String(36)
