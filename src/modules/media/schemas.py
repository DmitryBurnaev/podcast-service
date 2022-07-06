from marshmallow import Schema
from webargs import fields

__all__ = [
    "FileUploadSchema",
    "AudioFileResponseSchema",
]


class FileUploadSchema(Schema):
    file = fields.Raw(required=True)


class AudioFileResponseSchema(Schema):
    title = fields.Str()
    duration = fields.Int()
    path = fields.Str()
    size = fields.Int()
