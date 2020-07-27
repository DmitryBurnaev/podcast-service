import enum
import uuid
from datetime import datetime
from hashlib import md5
from urllib.parse import urljoin
from xml.sax.saxutils import escape

from common.db_utils import EnumTypeColumn
from core import settings
from core.database import db

from common.i18n import get_text_translation as _


class Podcast(db.Model):
    """ Simple model for saving podcast in DB """

    __tablename__ = "podcast_podcasts"

    id = db.Column(db.Integer, primary_key=True)
    publish_id = db.Column(db.String(length=32), unique=True, nullable=False)
    name = db.Column(db.String(length=256), nullable=False)
    description = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    download_automatically = db.Column(db.Boolean, default=True)
    rss_link = db.Column(db.String(length=128))
    image_url = db.Column(db.String(length=512))
    created_by_id = db.Column(db.Integer(), db.ForeignKey("auth_users.id"))

    def __str__(self):
        return f'<Podcast #{self.id} "{self.name}">'

    @property
    def safe_image_url(self) -> str:
        image_url = self.image_url
        if not image_url:
            image_url = urljoin(settings.S3_STORAGE_URL, settings.S3_DEFAULT_PODCAST_IMAGE)

        return image_url

    @classmethod
    async def create_first_podcast(cls, user_id: int):
        return await Podcast.create(
            publish_id=cls.generate_publish_id(),
            name=_("Your first podcast"),
            description=_(
                "Add new episode -> wait for downloading -> copy podcast RSS-link "
                "-> past this link to your podcast application -> enjoy".strip()
            ),
            created_by_id=user_id,
        )

    @classmethod
    def generate_publish_id(cls):
        return md5(uuid.uuid4().hex.encode("utf-8")).hexdigest()[::2]


class Episode(db.Model):
    """ Simple model for saving episodes in DB """
    __tablename__ = "podcast_episodes"

    class Status(enum.Enum):
        NEW = "new"
        DOWNLOADING = "downloading"
        PUBLISHED = "published"
        ARCHIVED = "archived"
        ERROR = "error"

    PROGRESS_STATUSES = (Status.DOWNLOADING, Status.ERROR)

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.String(length=32), index=True, nullable=False)
    podcast_id = db.Column(db.Integer, db.ForeignKey("podcast_podcasts.id"), index=True)
    title = db.Column(db.String(length=256), nullable=False)
    watch_url = db.Column(db.String(length=128))
    remote_url = db.Column(db.String(length=128))
    image_url = db.Column(db.String(length=512))
    length = db.Column(db.Integer, default=0)
    description = db.Column(db.String)
    file_name = db.Column(db.String(length=128))
    file_size = db.Column(db.Integer, default=0)
    author = db.Column(db.String(length=256))
    status = EnumTypeColumn(Status, impl=db.String(16), default=Status.NEW, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    published_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey("auth_users.id"), index=True)

    class Meta:
        order_by = ("-published_at",)
        db_table = "podcast_episodes"

    def __str__(self):
        return f'<Episode #{self.id} {self.source_id} [{self.status}] "{self.title[:10]}..." >'

    @classmethod
    async def get_in_progress(cls, user_id):
        """ Return downloading episodes """
        return await (
            Episode.query.where(
                Episode.status.in_(Episode.PROGRESS_STATUSES),
                Episode.created_by_id == user_id
            ).order_by(
                Episode.created_at.desc()
            )
        )

    @property
    def safe_image_url(self) -> str:
        return escape(self.image_url or "")

    @property
    def content_type(self) -> str:
        file_name = self.file_name or "unknown"
        return f"audio/{file_name.split('.')[-1]}"
