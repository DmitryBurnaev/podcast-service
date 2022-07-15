from marshmallow import Schema
from webargs import fields

__all__ = [
    "FileUploadSchema",
    "AudioFileResponseSchema",
]


class FileUploadSchema(Schema):
    file = fields.Raw(required=True)


class MetaDataSchema(Schema):
    title = fields.Str()
    duration = fields.Int()
    author = fields.Str()
    album = fields.Str()


class AudioFileResponseSchema(Schema):
    path = fields.Str()
    size = fields.Int()
    metadata = fields.Nested(MetaDataSchema)
