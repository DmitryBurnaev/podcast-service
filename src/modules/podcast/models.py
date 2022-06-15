import os
import uuid
from functools import cached_property
from hashlib import md5
from datetime import datetime

from sqlalchemy.orm import relationship
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text

from core import settings
from core.database import ModelBase
from common.utils import get_logger
from common.models import ModelMixin
from common.db_utils import EnumTypeColumn
from common.enums import SourceType, EpisodeStatus
from modules.media.models import File  # noqa (need for sqlalchemy's relationships)

logger = get_logger(__name__)


class Podcast(ModelBase, ModelMixin):
    """SQLAlchemy schema for podcast instances"""

    __tablename__ = "podcast_podcasts"

    id = Column(Integer, primary_key=True)
    publish_id = Column(String(length=32), unique=True, nullable=False)
    name = Column(String(length=256), nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    download_automatically = Column(Boolean, default=True)
    # TODO: remove from DB's schema
    # rss_link = Column(String(length=128))
    # image_url = Column(String(length=512))
    rss_id = Column(Integer, ForeignKey("media_files.id", ondelete="SET NULL"))
    image_id = Column(Integer, ForeignKey("media_files.id", ondelete="SET NULL"))
    owner_id = Column(Integer, ForeignKey("auth_users.id"))

    episodes = relationship("Episode")
    rss = relationship("File", foreign_keys=[rss_id], lazy="subquery")
    image = relationship("File", foreign_keys=[image_id], lazy="subquery")

    def __str__(self):
        return f'<Podcast #{self.id} "{self.name}">'

    @property
    def image_url(self) -> str:
        return self.image.url if self.image else settings.DEFAULT_PODCAST_COVER

    @classmethod
    async def create_first_podcast(cls, db_session: AsyncSession, user_id: int):
        return await Podcast.async_create(
            db_session,
            publish_id=cls.generate_publish_id(),
            name="Your podcast",
            description=(
                "Add new episode -> wait for downloading -> copy podcast RSS-link "
                "-> past this link to your podcast application -> enjoy".strip()
            ),
            owner_id=user_id,
        )

    @classmethod
    def generate_publish_id(cls) -> str:
        return md5(uuid.uuid4().hex.encode("utf-8")).hexdigest()[::2]

    def generate_image_name(self) -> str:
        return f"{self.publish_id}_{uuid.uuid4().hex}.png"


class Episode(ModelBase, ModelMixin):
    """SQLAlchemy schema for episode instances"""

    __tablename__ = "podcast_episodes"
    Status = EpisodeStatus
    Sources = SourceType
    PROGRESS_STATUSES = (Status.DOWNLOADING,)

    id = Column(Integer, primary_key=True)
    title = Column(String(length=256), nullable=False)
    source_id = Column(String(length=32), index=True, nullable=False)
    source_type = EnumTypeColumn(SourceType, default=SourceType.YOUTUBE, nullable=True)
    podcast_id = Column(Integer, ForeignKey("podcast_podcasts.id", ondelete="CASCADE"), index=True)
    audio_id = Column(Integer, ForeignKey("media_files.id", ondelete="SET NULL"))
    image_id = Column(Integer, ForeignKey("media_files.id", ondelete="SET NULL"))
    owner_id = Column(Integer, ForeignKey("auth_users.id"), index=True)
    cookie_id = Column(Integer, ForeignKey("podcast_cookies.id", ondelete="SET NULL"))
    watch_url = Column(String(length=128))
    # TODO: remove that fields (remote_url | image_url) from DB too
    # remote_url = Column(String(length=128))
    # image_url = Column(String(length=512))
    length = Column(Integer, default=0)
    description = Column(String)
    # file_name = Column(String(length=128))
    # file_size = Column(Integer, default=0)
    author = Column(String(length=256))
    status = EnumTypeColumn(Status, default=Status.NEW, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)

    # TODO: recheck extra queries here
    image = relationship("File", foreign_keys=[image_id], lazy="subquery")
    audio = relationship("File", foreign_keys=[audio_id], lazy="subquery")

    class Meta:
        order_by = ("-created_at",)

    def __str__(self) -> str:
        return f'<Episode #{self.id} {self.source_id} [{self.status}] "{self.title[:10]}..." >'

    @classmethod
    async def get_in_progress(cls, db_session: AsyncSession, user_id: int):
        """Return downloading episodes"""
        return await cls.async_filter(
            db_session, status__in=Episode.PROGRESS_STATUSES, owner_id=user_id
        )

    @property
    def image_url(self) -> str:
        if self.image and self.image.available:
            return self.image.url

        return settings.DEFAULT_EPISODE_COVER

    @cached_property
    def audio_filename(self) -> str:
        if not (filename := self.audio.name):
            suffix = md5(f"{self.source_id}-{settings.FILENAME_SALT}".encode()).hexdigest()
            filename = f"{self.source_id}_{suffix}.mp3"

        return filename

    @classmethod
    def generate_image_name(cls, source_id: str) -> str:
        return f"{source_id}_{uuid.uuid4().hex}.png"

    async def delete(self, db_session: AsyncSession, db_flush: bool = True):
        """Removing files associated with requested episode"""

        if self.image_id:
            await self.image.delete(
                db_session, db_flush, remote_path=settings.S3_BUCKET_EPISODE_IMAGES_PATH
            )

        if self.audio_id:
            await self.audio.delete(db_session, db_flush)

        return await super().delete(db_session, db_flush)


class Cookie(ModelBase, ModelMixin):
    """Saving cookies (in netscape format) for accessing to auth-only resources"""

    __tablename__ = "podcast_cookies"

    id = Column(Integer, primary_key=True)
    source_type = EnumTypeColumn(SourceType)
    data = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    owner_id = Column(Integer, ForeignKey("auth_users.id"))

    class Meta:
        order_by = ("-created_at",)

    def __str__(self):
        return f'<Cookie #{self.id} "{self.domain}" at {self.created_at}>'

    def as_file(self) -> str:
        cookies_file = settings.TMP_COOKIES_PATH / f"cookie_{self.source_type}_{self.id}.txt"
        # TODO: can we use async API for this files IO-operations?
        if not os.path.exists(cookies_file):
            logger.info(f"Cookie #{self.id}: Generation cookie file [{cookies_file}]")
            with open(cookies_file, "wt") as fh:
                fh.write(self.data)
        else:
            logger.info(f"Cookie #{self.id}: Found already generated file [{cookies_file}]")

        return cookies_file
