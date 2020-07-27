import enum
from typing import TypeVar

from core.database import db


DBModel = TypeVar("DBModel", bound=db.Model)
EnumClass = TypeVar("EnumClass", bound=enum.Enum)
