from marshmallow import Schema
from webargs import fields, validate


__all__ = [
    "PodcastDetailsSchema",
    "PodcastCreateUpdateSchema",
    "EpisodeListSchema",
    "EpisodeCreateSchema",
    "EpisodeDetailsSchema",
    "EpisodeUpdateSchema",
    "PlayListRequestSchema",
    "PlayListResponseSchema",
    "ProgressResponseSchema",
]


class PodcastCreateUpdateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    description = fields.Str()
    download_automatically = fields.Bool(default=True)


class PodcastDetailsSchema(Schema):
    id = fields.Int(required=True)
    name = fields.Str(required=True)
    description = fields.Str(required=True)
    created_at = fields.DateTime(required=True)
    image_url = fields.URL()
    download_automatically = fields.Boolean(default=True)


class EpisodeCreateSchema(Schema):
    source_url = fields.URL(required=True)


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


class EpisodeDetailsSchema(Schema):
    id = fields.Int(required=True)
    title = fields.Str(required=True)
    author = fields.Str()
    status = fields.Str()
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


class ProgressResponseSchema(Schema):
    status = fields.Str()
    status_display = fields.Str()
    completed = fields.Float()
    current_file_size = fields.Int()
    total_file_size = fields.Int()
    episode = fields.Nested(ProgressEpisodeSchema)
    podcast = fields.Nested(ProgressPodcastSchema)
