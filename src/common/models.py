from gino import GinoEngine
from sqlalchemy import and_
from sqlalchemy.sql import Select

from core.database import db


class BaseModel(db.Model):
    """ Base model with db Meta """

    class Meta:
        order_by = ("id",)

    @classmethod
    def prepare_query(cls, **filter_kwargs) -> Select:
        filters = []
        for filter_name, filter_value in filter_kwargs.items():
            field, _, criteria = filter_name.partition("__")
            if criteria in ("eq", ""):
                filters.append((getattr(cls, field) == filter_value))
            elif criteria == "gt":
                filters.append((getattr(cls, field) > filter_value))
            elif criteria == "lt":
                filters.append((getattr(cls, field) < filter_value))
            else:
                raise NotImplementedError(f"Unexpected criteria: {criteria}")

        order_by = []
        for field in cls.Meta.order_by:
            if field.startswith("-"):
                order_by.append(getattr(cls, field.replace("-", "")).desc())
            else:
                order_by.append(getattr(cls, field))

        return cls.query.where(and_(*filters)).order_by(*order_by)

    @classmethod
    async def async_filter(cls, **filter_kwargs) -> "GinoEngine.all":
        query = cls.prepare_query(**filter_kwargs)
        return await query.gino.all()

    @classmethod
    async def async_get(cls, **filter_kwargs) -> "BaseModel":
        query = cls.prepare_query(**filter_kwargs)
        return await query.gino.first()
