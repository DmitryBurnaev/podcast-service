from marshmallow import Schema, EXCLUDE, post_load, ValidationError
from webargs import fields

__all__ = [
    "AudioFileUploadSchema",
    "AudioFileResponseSchema",
    "MetaDataSchema",
    "CoverSchema",
]


class AudioFileUploadSchema(Schema):
    file = fields.Raw(required=True)

    @post_load
    def validate_file(self, data, **_) -> dict:
        content_type = data["file"].content_type
        if not content_type.startswith("audio/"):
            raise ValidationError(f"File must be audio, not {content_type}", field_name="file")

        return data


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
