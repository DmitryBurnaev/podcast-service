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

logger = get_logger(__name__)


class File(ModelBase, ModelMixin):
    """Storing files separately allows supporting individual access for them"""

    __tablename__ = "media_files"

    id = Column(Integer, primary_key=True)
    type = EnumTypeColumn(FileType, nullable=False)
    path = Column(String(length=256), nullable=False)
    size = Column(Integer, default=0)
    source_url = Column(String(length=512), nullable=False, default="")
    available = Column(Boolean, nullable=False, default=False)
    access_token = Column(String(length=64), nullable=False, index=True, unique=True)
    owner_id = Column(Integer, ForeignKey("auth_users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __str__(self):
        return f'<File #{self.id} "{self.path}">'

    @classmethod
    def generate_token(cls) -> str:
        return get_random_hash(48)

    @property
    def url(self) -> str:
        return urllib.parse.urljoin(settings.SERVICE_URL, f"/m/{self.access_token}")

    @property
    def content_type(self) -> str:
        file_name = os.path.basename(self.path)
        return f"{self.type.lower()}/{file_name.split('.')[-1]}"

    async def delete(self, db_session: AsyncSession):
        same_files = await File.async_filter(
            db_session,
            path=self.path,
            id__ne=self.id,
            type=self.type,
            available__is=True
        )
        if not same_files.all():
            await StorageS3().delete_files_async([self.path])

        else:
            file_infos = [(file.id, file.type) for file in same_files]
            logger.warning(
                f"There are another relations for the file {self.path}: {file_infos}."
                f"Skip file removing."
            )

        return super(File, self).delete(db_session)
