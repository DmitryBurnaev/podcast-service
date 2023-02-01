from typing import Type

import sqlalchemy as sa
from sqlalchemy import Column
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


def make_session_maker() -> sessionmaker:
    db_engine = create_async_engine(settings.DATABASE_DSN, echo=settings.DB_ECHO)
    return sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
