from webargs import fields, validate
from starlette.datastructures import UploadFile
from marshmallow import Schema, validates, ValidationError

from core import settings
from common.schemas import WSRequestAuthSchema
from common.enums import SourceType, EpisodeStatus
from modules.media.schemas import MetaDataSchema, ImageUploadedSchema

__all__ = [
    "PodcastDetailsSchema",
    "PodcastCreateUpdateSchema",
    "EpisodeListRequestSchema",
    "EpisodeListSchema",
    "EpisodeCreateSchema",
    "EpisodeDetailsSchema",
    "EpisodeUpdateSchema",
    "PlayListRequestSchema",
    "PlayListResponseSchema",
    "ProgressResponseSchema",
    "PodcastUploadImageResponseSchema",
    "CookieCreateUpdateSchema",
    "CookieResponseSchema",
    "EpisodeUploadedSchema",
    "WSProgressRequestSchema",
]


class BaseLimitOffsetSchema(Schema):
    limit = fields.Int(required=False)
    offset = fields.Int(required=False)

    def load(self, *args, **kwargs):
        data = super().load(*args, **kwargs)
        data["limit"] = data.get("limit") or settings.DEFAULT_LIMIT_LIST_API
        data["offset"] = data.get("offset") or 0
        return data


class PodcastCreateUpdateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    description = fields.Str()
    download_automatically = fields.Bool(load_default=False)


class PodcastDetailsSchema(Schema):
    id = fields.Int(required=True)
    name = fields.Str(required=True)
    description = fields.Str(required=True)
    created_at = fields.DateTime(required=True)
    image_url = fields.URL(attribute="image.url")
    rss_url = fields.URL(attribute="rss.url")
    download_automatically = fields.Boolean(dump_default=True)
    episodes_count = fields.Integer(dump_default=0)


class PodcastUploadImageResponseSchema(Schema):
    id = fields.Int(required=True)
    image_url = fields.URL(attribute="image.url")


class EpisodeCreateSchema(Schema):
    source_url = fields.URL(required=True)


class EpisodeListRequestSchema(BaseLimitOffsetSchema):
    q = fields.Str(load_default="")
    status = fields.Str(validate=validate.OneOf(EpisodeStatus.members()))


class EpisodeUpdateSchema(Schema):
    title = fields.Str(validate=validate.Length(max=256))
    description = fields.Str()
    author = fields.Str(validate=validate.Length(max=256))


class EpisodeUploadedSchema(Schema):
    path = fields.Str(required=True, validate=validate.Length(max=256))
    name = fields.Str(required=True, validate=validate.Length(max=256))
    size = fields.Int(required=True)
    hash = fields.Str(required=True, validate=validate.Length(max=32))
    meta = fields.Nested(MetaDataSchema)
    cover = fields.Nested(ImageUploadedSchema, allow_none=True)


class EpisodeListSchema(Schema):
    id = fields.Int(required=True)
    title = fields.Str(required=True)
    created_at = fields.DateTime(required=True)
    image_url = fields.URL()
    status = fields.Str(required=True)
    source_type = fields.Str(required=True)


class PodcastInEpisodeSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    image_url = fields.URL()


class EpisodeChapterSchema(Schema):
    title = fields.Str()
    start = fields.Str(attribute="start_str")
    end = fields.Str(attribute="end_str")


class EpisodeDetailsSchema(Schema):
    id = fields.Int(required=True)
    title = fields.Str(required=True)
    author = fields.Str()
    status = fields.Str()
    status_display = fields.Str()
    length = fields.Int(required=True)
    audio_url = fields.URL(attribute="audio.url")
    audio_size = fields.Int(attribute="audio.size")
    image_url = fields.URL()
    watch_url = fields.URL()
    description = fields.Str()
    source_type = fields.Str(required=True)
    created_at = fields.DateTime(required=True)
    published_at = fields.DateTime(required=True, allow_none=True)
    podcast = fields.Nested(PodcastInEpisodeSchema)
    chapters = fields.Nested(EpisodeChapterSchema, many=True, attribute="list_chapters")


class PlayListRequestSchema(Schema):
    url = fields.URL()


class PlayListEntitySchema(Schema):
    id = fields.Str()
    title = fields.Str()
    description = fields.Str()
    thumbnail_url = fields.URL()
    url = fields.URL()


class PlayListResponseSchema(Schema):
    id = fields.Str()
    title = fields.Str()
    entries = fields.Nested(PlayListEntitySchema, many=True)


class ProgressPodcastSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    image_url = fields.URL()


class ProgressEpisodeSchema(Schema):
    id = fields.Int()
    title = fields.Str()
    image_url = fields.URL()
    status = fields.Str()


class ProgressResponseSchema(Schema):
    status = fields.Str()
    status_display = fields.Str()
    completed = fields.Float()
    current_file_size = fields.Int()
    total_file_size = fields.Int()
    episode = fields.Nested(ProgressEpisodeSchema)
    podcast = fields.Nested(ProgressPodcastSchema)


class CookieCreateUpdateSchema(Schema):
    source_type = fields.Str(required=True, validate=validate.OneOf(SourceType.__members__.keys()))
    file = fields.Raw(required=True, metadata={"type": "file"})

    @validates("file")
    def file_validator(self, value):
        if not isinstance(value, UploadFile):
            raise ValidationError(f"Required file's type here, found; {type(value)}")


class CookieResponseSchema(Schema):
    id = fields.Int()
    source_type = fields.Str(data_key="sourceType")
    created_at = fields.DateTime(data_key="createdAt")


class WSProgressRequestSchema(WSRequestAuthSchema):
    episode_id = fields.Int(data_key="episodeID")


class HealthCheckResponseSchema(Schema):
    status = fields.Str()


class SystemInfoResponseSchema(Schema):
    version = fields.Str()
