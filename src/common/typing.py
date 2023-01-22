import enum
from typing import TypeVar

from common.enums import StringEnum


EnumT = TypeVar("EnumT", bound=enum.Enum)
StringEnumT = TypeVar("StringEnumT", bound=StringEnum)
T = TypeVar("T")
