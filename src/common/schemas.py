from marshmallow import fields, Schema


class WSHeadersRequestSchema(Schema):
    authorization = fields.Str()


class WSRequestAuthSchema(Schema):
    headers = fields.Nested(WSHeadersRequestSchema())
