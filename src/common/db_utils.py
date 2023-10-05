from typing import Type, cast

import sqlalchemy as sa
from sqlalchemy import Column, Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from core import settings
from common.typing import StringEnumT


# pylint: disable=too-many-ancestors,abstract-method
class EnumTypeColumn(Column):
    """
    Allows to define DB-native enum's columns

    >>> import enum
    >>> from core.database import ModelBase
    >>> from common.enums import StringEnumMixin

    >>> class UserType(StringEnumMixin, enum.StrEnum):
    >>>    ADMIN = 'ADMIN'
    >>>    REGULAR = 'REGULAR'

    >>> class User(ModelBase):
    >>>     ...
    >>>     type = EnumTypeColumn(UserType, default=UserType.ADMIN)

    >>> user = User(type=UserType.ADMIN)
    >>> user.type
    [0] <UserType.ADMIN: 'ADMIN'>

    """

    def __new__(cls, enum_class: Type[StringEnumT], **kwargs):
        if "nullable" not in kwargs:
            kwargs["nullable"] = False

        return Column(sa.Enum(*enum_class.members(), name=enum_class.__enum_name__), **kwargs)


# pylint: disable=line-too-long
def make_session_maker() -> sessionmaker:
    """
    Provides DB's session for async context.
    Using disabled JIT ("jit": "off") fixes asyncpg improvements problem with native enums
    see for details https://docs.sqlalchemy.org/en/14/dialects/postgresql.html#disabling-the-postgresql-jit-to-improve-enum-datatype-handling
    """
    async_engine = create_async_engine(
        settings.DATABASE_DSN,
        echo=settings.DB_ECHO,
        connect_args={"server_settings": {"jit": "off"}},
    )
    db_engine = cast(Engine, async_engine)  # just for correct typing
    return sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
