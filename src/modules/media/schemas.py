from marshmallow import Schema, EXCLUDE
from webargs import fields

__all__ = [
    "FileUploadSchema",
    "AudioFileResponseSchema",
    "MetaDataSchema",
]


class FileUploadSchema(Schema):
    file = fields.Raw(required=True)


class CoverSchema(Schema):
    path = fields.Str()
    hash = fields.Str()
    size = fields.Int()
    preview_url = fields.Str(dump_only=True)

    class Meta:
        unknown = EXCLUDE


class MetaDataSchema(Schema):
    duration = fields.Int(required=True)
    title = fields.Str()
    author = fields.Str()
    album = fields.Str()
    track = fields.Str()


class AudioFileResponseSchema(Schema):
    name = fields.Str(required=True)
    path = fields.Str(required=True)
    size = fields.Int(required=True)
    meta = fields.Nested(MetaDataSchema)
    hash = fields.Str(required=True)
    cover = fields.Nested(CoverSchema)
