import os.path
import urllib.parse
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.asyncio import AsyncSession

from common.storage import StorageS3
from core import settings
from core.database import ModelBase
from common.enums import FileType
from common.utils import get_logger
from common.models import ModelMixin
from common.db_utils import EnumTypeColumn
from modules.auth.hasher import get_random_hash

# TODO: fix strange behavior (import is needed for working with FK "owner_id")
from modules.auth.models import User  # noqa

logger = get_logger(__name__)
REMOTE_PATH_MAP = {
    FileType.AUDIO: settings.S3_BUCKET_AUDIO_PATH,
    FileType.RSS: settings.S3_BUCKET_RSS_PATH,
}
TOKEN_LENGTH = 48


class File(ModelBase, ModelMixin):
    """Storing files separately allows supporting individual access for them"""

    __tablename__ = "media_files"

    id = Column(Integer, primary_key=True)
    type = EnumTypeColumn(FileType, nullable=False)
    path = Column(String(length=256), nullable=False, default="")
    size = Column(Integer, default=0)
    source_url = Column(String(length=512), nullable=False, default="")
    available = Column(Boolean, nullable=False, default=False)
    access_token = Column(String(length=64), nullable=False, index=True, unique=True)
    owner_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __str__(self):
        return f'<File #{self.id} | {self.type} | "{self.path}">'

    @classmethod
    def generate_token(cls) -> str:
        return get_random_hash(TOKEN_LENGTH)

    @classmethod
    def token_is_correct(cls, token: str) -> bool:
        return token.isalnum() and len(token) == TOKEN_LENGTH

    @property
    def url(self) -> str:
        path = f"/r/{self.access_token}" if self.type == FileType.RSS else f"/m/{self.access_token}"
        return urllib.parse.urljoin(settings.SERVICE_URL, path)

    @property
    async def remote_url(self) -> str:
        url = await StorageS3().get_file_url(self.path)
        logger.debug("Generated URL for %s: %s", self, url)
        return url

    @property
    def content_type(self) -> str:
        return f"{self.type.lower()}/{self.name.split('.')[-1]}"

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    async def delete(
        self, db_session: AsyncSession, db_flush: bool = True, remote_path: str = None
    ):
        same_files = (
            await File.async_filter(
                db_session, path=self.path, id__ne=self.id, type=self.type, available__is=True
            )
        ).all()
        if not same_files:
            remote_path = remote_path or REMOTE_PATH_MAP[self.type]
            await StorageS3().delete_files_async([self.name], remote_path=remote_path)

        else:
            file_infos = [(file.id, file.type.value) for file in same_files]
            logger.warning(
                "There are another relations for the file %s: %s. Skip file removing.",
                self.path,
                file_infos,
            )

        return await super(File, self).delete(db_session, db_flush)

    @classmethod
    async def create(
        cls,
        db_session: AsyncSession,
        file_type: FileType,
        available: bool = True,
        **file_kwargs,
    ) -> "File":
        file_kwargs = file_kwargs | {
            "available": available,
            "access_token": File.generate_token(),
            "type": file_type,
        }
        logger.debug("Creating new file: %s", file_kwargs)
        return await File.async_create(db_session=db_session, **file_kwargs)

    @classmethod
    async def copy(
        cls, db_session: AsyncSession, file_id: int, owner_id: int, available: bool = True
    ) -> "File":
        source_file: File = await File.async_get(db_session, id=file_id)
        logger.debug("Copying file: source %s | owner_id %s", source_file, owner_id)
        return await File.create(
            db_session,
            source_file.type,
            owner_id=owner_id,
            available=available,
            path=source_file.path,
            size=source_file.size,
            source_url=source_file.source_url,
        )
