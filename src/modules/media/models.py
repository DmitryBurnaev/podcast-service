import os.path
import urllib.parse
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.asyncio import AsyncSession

from common.exceptions import NotSupportedError
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
    public = Column(Boolean, nullable=False, default=False)

    def __repr__(self):
        return f'<File #{self.id} | {self.type} | "{self.path}">'

    @classmethod
    def generate_token(cls) -> str:
        return get_random_hash(TOKEN_LENGTH)

    @classmethod
    def token_is_correct(cls, token: str) -> bool:
        return token.isalnum() and len(token) == TOKEN_LENGTH

    @property
    def url(self) -> str:
        if self.public:
            if self.source_url:
                # TODO: upload with acl instead
                return self.source_url

            return urllib.parse.urljoin(
                settings.S3_STORAGE_URL, f"{settings.S3_BUCKET_NAME}/{self.path}"
            )

        pattern = {
            FileType.RSS: f"/r/{self.access_token}/",
            FileType.IMAGE: f"/m/{self.access_token}/",
            FileType.AUDIO: f"/m/{self.access_token}/",
        }
        return urllib.parse.urljoin(settings.SERVICE_URL, pattern[self.type])

    @property
    async def presigned_url(self) -> str:
        if self.available and not self.path:
            raise NotSupportedError(f"Remote file {self} available but has not remote path.")

        url = await StorageS3().get_presigned_url(self.path)
        logger.debug("Generated URL for %s: %s", self, url)
        return url

    @property
    def content_type(self) -> str:
        return f"{self.type.value.lower()}/{self.name.split('.')[-1]}"

    @property
    def headers(self) -> dict:
        return {"content-length": str(self.size or 0), "content-type": self.content_type}

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    async def delete(
        self, db_session: AsyncSession, db_flush: bool = True, remote_path: str = None
    ):
        filter_kwargs = {"path": self.path, "id__ne": self.id, "available__is": True}
        if same_files := (await File.async_filter(db_session, **filter_kwargs)).all():
            file_infos = [(file.id, file.type.value) for file in same_files]
            logger.warning(
                "There are another relations for the file %s: %s. Skip file removing.",
                self.path,
                file_infos,
            )

        elif not self.available:
            logger.debug("Skip deleting not-available file: %s", self)

        else:
            remote_path = remote_path or REMOTE_PATH_MAP[self.type]
            logger.debug("Removing file from S3: %s | called by: %s", remote_path, self)
            await StorageS3().delete_files_async([self.name], remote_path=remote_path)

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
