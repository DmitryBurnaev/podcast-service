import os
import uuid
import logging
from contextlib import asynccontextmanager
from hashlib import md5
from pathlib import Path
from functools import cached_property
from typing import AsyncContextManager, TypedDict

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from starlette.concurrency import run_in_threadpool

from core import settings
from core.database import ModelBase
from common.utils import utcnow
from common.models import ModelMixin
from common.db_utils import EnumTypeColumn
from common.encryption import SensitiveData
from common.exceptions import UnexpectedError
from common.enums import SourceType, EpisodeStatus
from modules.podcast.utils import delete_file

# pylint: disable=unused-import
from modules.media.models import File  # noqa (need for sqlalchemy's relationships)

logger = logging.getLogger(__name__)


class Podcast(ModelBase, ModelMixin):
    """SQLAlchemy schema for podcast instances"""

    __tablename__ = "podcast_podcasts"

    id = Column(Integer, primary_key=True)
    publish_id = Column(String(length=32), unique=True, nullable=False)
    name = Column(String(length=256), nullable=False)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    download_automatically = Column(Boolean, default=True)

    rss_id = Column(ForeignKey("media_files.id", ondelete="SET NULL"))
    image_id = Column(ForeignKey("media_files.id", ondelete="SET NULL"))
    owner_id = Column(ForeignKey("auth_users.id"))

    # relations
    rss = relationship("File", foreign_keys=[rss_id], lazy="subquery")
    image = relationship("File", foreign_keys=[image_id], lazy="subquery")

    def __str__(self):
        return f'<Podcast #{self.id} "{self.name}">'

    @property
    def image_url(self) -> str:
        url = self.image.url if self.image else None
        return url or settings.DEFAULT_PODCAST_COVER

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


class EpisodeChapter(TypedDict):
    """Base structure for each element of episode.chapters"""

    title: str
    start: str  # ex.: 0:45:05
    end: str  # ex.: 1:15:00


class Episode(ModelBase, ModelMixin):
    """SQLAlchemy schema for episode instances"""

    __tablename__ = "podcast_episodes"

    Status = EpisodeStatus
    Sources = SourceType
    PROGRESS_STATUSES = (EpisodeStatus.DOWNLOADING, EpisodeStatus.CANCELING)

    id = Column(Integer, primary_key=True)
    title = Column(String(length=256), nullable=False)
    source_id = Column(String(length=32), index=True, nullable=False)
    source_type = EnumTypeColumn(SourceType, default=SourceType.YOUTUBE)
    podcast_id = Column(ForeignKey("podcast_podcasts.id", ondelete="RESTRICT"), index=True)
    audio_id = Column(ForeignKey("media_files.id", ondelete="SET NULL"))
    image_id = Column(ForeignKey("media_files.id", ondelete="SET NULL"))
    owner_id = Column(ForeignKey("auth_users.id"), index=True)
    cookie_id = Column(ForeignKey("podcast_cookies.id", ondelete="SET NULL"))
    watch_url = Column(String(length=128))
    length = Column(Integer, default=0)
    description = Column(String)
    chapters = Column(JSONB(none_as_null=True), nullable=True)  # JSON list of `EpisodeChapter`
    author = Column(String(length=256))
    status = EnumTypeColumn(EpisodeStatus, default=EpisodeStatus.NEW)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    published_at = Column(DateTime(timezone=True))

    # relations
    podcast = relationship("Podcast", lazy="subquery", backref="episodes")
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
        url = self.image.url if self.image else None
        return url or settings.DEFAULT_EPISODE_COVER

    @property
    def audio_url(self) -> str:
        url = self.audio.url if self.audio else None
        if not url and self.status == EpisodeStatus.PUBLISHED:
            raise UnexpectedError(
                "Can't retrieve audio_url for published episode without available audio file"
            )
        return url or settings.DEFAULT_EPISODE_COVER

    @property
    def list_chapters(self) -> list[EpisodeChapter]:
        return [EpisodeChapter(**chapter) for chapter in self.chapters] if self.chapters else []

    @property
    def rss_description(self) -> str:
        cleared_description = self.description.replace("[LINK]", "")
        paragraphs = cleared_description.split("\n")
        result = ""
        for paragraph in paragraphs:
            if paragraph:
                result += f"<p>{paragraph}</p>"
        return result

    @cached_property
    def audio_filename(self) -> str:
        filename = self.audio.name
        if not filename or "tmp" in self.audio.path:
            suffix = md5(f"{self.source_id}-{settings.FILENAME_SALT}".encode()).hexdigest()
            _, ext = os.path.splitext(filename)
            filename = f"{self.source_id}_{suffix}{ext or '.mp3'}"

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
    # __file_path: Path | None = None

    id = Column(Integer, primary_key=True)
    source_type = EnumTypeColumn(SourceType)
    data = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    owner_id = Column(ForeignKey("auth_users.id"))

    class Meta:
        order_by = ("-created_at",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__file_path: Path | None = None

    def __str__(self):
        return f'<Cookie #{self.id} "{self.source_type}" at {self.created_at}>'

    async def as_file(self) -> Path:
        """Library for downloading content takes only path to cookie's file (stored on the disk)"""

        def store_tmp_file():
            cookies_file = settings.TMP_COOKIES_PATH / f"cookie_{self.source_type}_{self.id}.txt"
            if not os.path.exists(cookies_file):
                logger.debug("Cookie #%s: Generation tmp cookie file [%s]", self.id, cookies_file)
                with open(cookies_file, "wt", encoding="utf-8") as f:
                    decr_data = SensitiveData().decrypt(self.data)
                    f.write(decr_data)
            else:
                logger.debug("Cookie #%s: Found already generated file [%s]", self.id, cookies_file)

            return cookies_file

        return await run_in_threadpool(store_tmp_file)

    @classmethod
    def get_encrypted_data(cls, data: str) -> str:
        """Return encrypted value for provided in `data` argument"""
        return SensitiveData().encrypt(data)

    @property
    def file_path(self):
        return self.__file_path

    @file_path.setter
    def file_path(self, value):
        self.__file_path = value


@asynccontextmanager
async def cookie_file_ctx(
    db_session: AsyncSession,
    user_id: int | None = None,
    source_type: SourceType | None = None,
    cookie_id: int | None = None,
) -> AsyncContextManager[Cookie | None]:
    """
    Async context which allows to save tmp file (with decrypted cookie's data)
    and remove it after using (by sec reason)

    :param db_session: current SA's async session
    :param user_id: current logged-in user (needed for searching cookie)
    :param source_type: required source (needed for searching cookie)
    :param cookie_id: if known - will be used for direct access

    """
    logger.debug(
        "Entering cookie's file context: user %s | source_type: %s | cookie_id: %s",
        user_id,
        source_type,
        cookie_id,
    )
    if cookie_id:
        cookie: Cookie | None = await Cookie.async_get(db_session, id=cookie_id)
    elif user_id and source_type:
        cookie_filter = {"source_type": source_type, "owner_id": user_id}
        cookie: Cookie | None = await Cookie.async_get(db_session, **cookie_filter)
    else:
        cookie = None

    if cookie:
        cookie.file_path = await cookie.as_file()
        yield cookie
        delete_file(cookie.file_path)
    else:
        yield None
