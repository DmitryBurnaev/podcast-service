import enum
from typing import TypeVar

# from core.database import BaseModel
from common.models import ModelMixin


DBModel = TypeVar("DBModel", bound=ModelMixin)
EnumClass = TypeVar("EnumClass", bound=enum.Enum)
