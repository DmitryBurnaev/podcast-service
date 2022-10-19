import enum
from typing import TypeVar

# from core.database import BaseModel


EnumClass = TypeVar("EnumClass", bound=enum.Enum)
T = TypeVar('T')
