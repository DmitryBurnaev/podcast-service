import collections
from typing import Union, List

from pydantic.main import BaseModel

from common.typing import DBModel


class Serializer(BaseModel):
    """ Alias for `pydantic.main.BaseModel` """
    ...


class ModelSerializer(BaseModel):
    """ Shortcut for ORM-based pydantic models (ex.: serializing data for response) """

    @classmethod
    def from_orm(cls, obj: Union[DBModel, List[DBModel]]) -> Union[BaseModel, List[BaseModel]]:
        """ Return single instance or list of `ModelSerializer` """

        if isinstance(obj, collections.Iterable):
            return [cls.from_orm(item) for item in obj]

        return super().from_orm(obj)

    class Config:
        orm_mode = True
