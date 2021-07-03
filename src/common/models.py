from typing import TypeVar

from sqlalchemy import and_, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select


class ModelMixin:
    """ Base model for Gino (sqlalchemy) ORM """

    class Meta:
        order_by = ("id",)

    @classmethod
    def prepare_query(cls, **filter_kwargs) -> Select:
        order_by = []
        for field in cls.Meta.order_by:
            if field.startswith("-"):
                order_by.append(getattr(cls, field.replace("-", "")).desc())
            else:
                order_by.append(getattr(cls, field))

        return select(cls).filter(cls._filter_criteria(filter_kwargs)).order_by(*order_by)

    @classmethod
    async def async_filter(cls, db_session: AsyncSession, **filter_kwargs) -> list["DBModel"]:
        query = cls.prepare_query(**filter_kwargs)
        result = await db_session.execute(query)
        return await result.all()

    @classmethod
    async def async_get(cls, db_session: AsyncSession, **filter_kwargs) -> "DBModel":
        query = cls.prepare_query(**filter_kwargs)
        result = await db_session.execute(query)
        return await result.fetchone()

    @classmethod
    async def async_update(cls, db_session: AsyncSession, filter_kwargs: dict, update_data: dict):
        query = (
            db_session.query(cls)
            .filter(**cls._filter_criteria(filter_kwargs))
            .update(**update_data)
        )
        result: Result = await db_session.execute(query)
        # TODO: we need to return another result (may be)...
        return await result.first()

    @classmethod
    async def create(cls, db_session: AsyncSession, **data):
        async with db_session.begin():
            instance = cls(**data)  # noqa
            db_session.add_all([instance])
            await db_session.commit()

        return instance

    @classmethod
    def _filter_criteria(cls, filter_kwargs):
        filters = []
        for filter_name, filter_value in filter_kwargs.items():
            field, _, criteria = filter_name.partition("__")
            if criteria in ("eq", ""):
                filters.append((getattr(cls, field) == filter_value))
            elif criteria == "gt":
                filters.append((getattr(cls, field) > filter_value))
            elif criteria == "lt":
                filters.append((getattr(cls, field) < filter_value))
            elif criteria == "is":
                filters.append((getattr(cls, field).is_(filter_value)))
            elif criteria == "in":
                filters.append((getattr(cls, field).in_(filter_value)))
            elif criteria == "ne":
                filters.append((getattr(cls, field) != filter_value))
            else:
                raise NotImplementedError(f"Unexpected criteria: {criteria}")

        return and_(*filters)


DBModel = TypeVar("DBModel", bound=ModelMixin)
