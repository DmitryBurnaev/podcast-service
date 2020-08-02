from sqlalchemy import and_

from core.database import db


class BaseModel(db.Model):
    """ Base model with db Meta """

    @classmethod
    async def async_get(cls, **filter_kwargs) -> "BaseModel":
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

        return await cls.query.where(and_(*filters)).gino.first()
