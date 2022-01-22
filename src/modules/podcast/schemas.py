from marshmallow import Schema
from webargs import fields, validate

from core import settings

__all__ = [
    "PodcastDetailsSchema",
    "PodcastCreateUpdateSchema",
    "EpisodeListRequestSchema",
    "EpisodeListResponseSchema",
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
]

from modules.podcast.models import SourceType


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
    image_url = fields.URL()
    rss_link = fields.URL()
    download_automatically = fields.Boolean(dump_default=True)
    episodes_count = fields.Integer(dump_default=0)


class PodcastUploadImageResponseSchema(Schema):
    id = fields.Int(required=True)
    image_url = fields.URL()


class EpisodeCreateSchema(Schema):
    source_url = fields.URL(required=True)


class EpisodeListRequestSchema(BaseLimitOffsetSchema):
    q = fields.Str(load_default="")


class EpisodeUpdateSchema(Schema):
    title = fields.Str(validate=validate.Length(max=256))
    description = fields.Str()
    author = fields.Str(validate=validate.Length(max=256))


class EpisodeListSchema(Schema):
    id = fields.Int(required=True)
    title = fields.Str(required=True)
    created_at = fields.DateTime(required=True)
    image_url = fields.URL()
    status = fields.Str(required=True)


class EpisodeListResponseSchema(Schema):
    has_next = fields.Bool()
    items = fields.Nested(EpisodeListSchema, many=True)


class EpisodeDetailsSchema(Schema):
    id = fields.Int(required=True)
    title = fields.Str(required=True)
    author = fields.Str()
    status = fields.Str()
    status_display = fields.Str()
    length = fields.Int(required=True)
    watch_url = fields.URL()
    remote_url = fields.URL()
    image_url = fields.URL()
    file_size = fields.Int()
    description = fields.Str()
    created_at = fields.DateTime(required=True)
    published_at = fields.DateTime(required=True, allow_none=True)


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
    source_type = fields.Str(
        required=True,
        validate=validate.OneOf(SourceType.__members__.keys())
    )
    file = fields.Raw()


class CookieResponseSchema(Schema):
    id = fields.Int()
    source_type = fields.Str()
    created_at = fields.DateTime()
