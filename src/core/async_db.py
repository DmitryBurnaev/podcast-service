"""Illustrates use of the sqlalchemy.ext.asyncio.AsyncSession object
for asynchronous ORM use.

"""

import asyncio
import os
from datetime import datetime

from sqlalchemy import Column, Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.future import select
from sqlalchemy.orm import relationship
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class Podcast(Base):
    __tablename__ = "podcast_podcasts"

    id = Column(Integer, primary_key=True)
    publish_id = Column(String(length=32), unique=True, nullable=False)
    name = Column(String(length=256), nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    download_automatically = Column(Boolean, default=True)
    rss_link = Column(String(length=128))
    image_url = Column(String(length=512))
    # created_by_id = Column(Integer(), ForeignKey("auth_users.id"))

    episodes = relationship("Episode")
    # required in order to access columns with server defaults
    # or SQL expression defaults, subsequent to a flush, without
    # triggering an expired load
    __mapper_args__ = {"eager_defaults": True}


class Episode(Base):
    """ Simple schema_request for saving episodes in DB """

    __tablename__ = "podcast_episodes"

    id = Column(Integer, primary_key=True)
    source_id = Column(String(length=32), index=True, nullable=False)
    podcast_id = Column(Integer, ForeignKey("podcast_podcasts.id", ondelete="CASCADE"), index=True)
    title = Column(String(length=256), nullable=False)


async def async_main():
    """Main program function."""

    engine = create_async_engine(
        os.getenv("DB_DSN"),
        echo=True,
    )

    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.drop_all)
    #     await conn.run_sync(Base.metadata.create_all)

    # expire_on_commit=False will prevent attributes from being expired
    # after commit.
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        # async with session.begin():
        #     session.add_all(
        #         [
        #             Podcast(bs=[Episode(), Episode()], data="a1"),
        #             Podcast(bs=[Episode()], data="a2"),
        #             Podcast(bs=[Episode(), Episode()], data="a3"),
        #         ]
        #     )

        # for relationship loading, eager loading should be applied.
        stmt = select(Podcast).options(selectinload(Podcast.episodes))

        # AsyncSession.execute() is used for 2.0 style ORM execution
        # (same as the synchronous API).
        result = await session.execute(stmt)

        # result is a buffered Result object.
        for a1 in result.scalars():
            print(a1)
            print(f"created at: {a1.name}")
            for episode in a1.episodes:
                print(episode.id, episode.title)

        # for streaming ORM results, AsyncSession.stream() may be used.
        result = await session.stream(stmt)

        # result is a streaming AsyncResult object.
        async for a1 in result.scalars():
            print(a1)
            for episode in a1.episodes:
                print(episode.title)

        result = await session.execute(select(Podcast).order_by(Podcast.id))

        podcast = result.scalars().first()
        podcast.name = f"{podcast.name} + 1"
        print(f"==== {podcast.name} ====")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(async_main())
