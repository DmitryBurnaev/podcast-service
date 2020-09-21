from typing import Optional

from marshmallow import Schema
from webargs import fields, validate


__all__ = [
    "PodcastListSchema",
    "PodcastDetailsSchema",
    "PodcastCreateUpdateSchema",
    "EpisodeListSchema",
    "EpisodeCreateSchema",
    "EpisodeDetailsSchema",
    "EpisodeUpdateSchema",
]


class PodcastCreateUpdateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    description = fields.Str()
    download_automatically = fields.Bool(required=False, default=True)


class PodcastListSchema(Schema):
    id = fields.Int(required=True)
    name = fields.Str(required=True)
    created_at = fields.DateTime(required=True)
    image_url: Optional[str]


class PodcastDetailsSchema(Schema):
    id = fields.Int(required=True)
    name = fields.Str(required=True)
    description = fields.Str(required=True)
    created_at = fields.DateTime(required=True)
    image_url = fields.URL()


class EpisodeCreateSchema(Schema):
    youtube_link = fields.URL()


class EpisodeUpdateSchema(Schema):
    title = fields.Str()
    description = fields.Str()
    author = fields.Str()


class EpisodeListSchema(Schema):
    id = fields.Int(required=True)
    title = fields.Str(required=True)
    created_at = fields.DateTime(required=True)
    image_url = fields.URL()


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
    description = fields.Str
    created_at = fields.DateTime(required=True)
    published_at = fields.DateTime(required=True, allow_none=True)
