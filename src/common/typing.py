import enum
from typing import TypeVar

from common.enums import StringEnumMixin


EnumT = TypeVar("EnumT", bound=enum.Enum)
StringEnumT = TypeVar("StringEnumT", bound=StringEnumMixin)
T = TypeVar("T")
