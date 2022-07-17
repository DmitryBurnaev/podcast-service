from marshmallow import Schema
from webargs import fields

__all__ = [
    "FileUploadSchema",
    "AudioFileResponseSchema",
]


class FileUploadSchema(Schema):
    file = fields.Raw(required=True)


class MetaDataSchema(Schema):
    duration = fields.Int(required=True)
    title = fields.Str()
    author = fields.Str()
    album = fields.Str()
    track = fields.Str()


class AudioFileResponseSchema(Schema):
    filename = fields.Str(required=True)
    path = fields.Str(required=True)
    size = fields.Int(required=True)
    meta = fields.Nested(MetaDataSchema)
