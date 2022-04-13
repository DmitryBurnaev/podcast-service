from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean

from core.database import ModelBase
from common.enums import FileType
from common.utils import get_logger
from common.models import ModelMixin
from common.db_utils import EnumTypeColumn


logger = get_logger(__name__)


class File(ModelBase, ModelMixin):
    """ Storing files separately allows supporting individual access for them """

    __tablename__ = "media_files"

    id = Column(Integer, primary_key=True)
    type = EnumTypeColumn(FileType)
    path = Column(String(length=256))
    size = Column(Integer, default=0)
    source_url = Column(String(length=512))
    available = Column(Boolean, default=False)
    access_token = Column(String(length=128), index=True)
    owner_id = Column(Integer, ForeignKey("auth_users.id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __str__(self):
        return f'<File #{self.id} "{self.path}">'

