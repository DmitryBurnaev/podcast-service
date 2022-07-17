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
    author = fields.Str(required=False)
    album = fields.Str(required=False)
    track = fields.Str(required=False)


class AudioFileResponseSchema(Schema):
    filename = fields.Str()
    path = fields.Str()
    size = fields.Int()
    meta = fields.Nested(MetaDataSchema)
