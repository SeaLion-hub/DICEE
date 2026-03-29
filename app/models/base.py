"""SQLAlchemy Declarative Base."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 신규 인덱스·FK·유니크·PK 이름 일관성 (기존 DB 객체 rename은 별 마이그레이션).
POSTGRES_NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """공통 베이스 클래스."""

    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)
