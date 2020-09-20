import typing
from marshmallow import Schema, ValidationError
from webargs import fields, validate


__all__ = [
    "SignInSchema",
    "SignUpSchema",
    "RefreshTokenSchema",
    "JWTResponseSchema",
    "UserInviteRequestSchema",
    "UserInviteResponseSchema",
    "ResetPasswordRequestSchema",
    "ResetPasswordResponseSchema",
    "ChangePasswordSchema",
    "UserResponseSchema",
]

from modules.auth.models import User


class TwoPasswordsMixin:

    def validate(self, data: typing.Mapping, *args, **kwargs) -> typing.Mapping:
        if data["password_1"] != data["password_2"]:
            raise ValidationError("Passwords should be equal")

        return data


class SignInSchema(Schema):
    email = fields.Email(required=True)
    password = fields.Str(required=True, validate=validate.Length(min=2, max=32))


class SignUpSchema(TwoPasswordsMixin, Schema):
    email = fields.Email(required=True)
    password_1 = fields.Str(required=True, validate=validate.Length(min=2, max=32))
    password_2 = fields.Str(required=True, validate=validate.Length(min=2, max=32))
    invite_token = fields.Str(required=True)

    def validate(self, data: typing.Mapping, *args, **kwargs) -> typing.Mapping:
        if data["password_1"] != data["password_2"]:
            raise ValidationError("Passwords should be equal")

        return data


class RefreshTokenSchema(Schema):
    refresh_token = fields.Str(required=True)


class JWTResponseSchema(Schema):
    access_token = fields.Str(required=True)
    refresh_token = fields.Str(required=True)

    class Meta:
        fields = ("access_token", "refresh_token")


class UserInviteRequestSchema(Schema):
    email = fields.Email(required=True)


class UserInviteResponseSchema(Schema):
    email = fields.Email(required=True)
    token = fields.Str(required=True)
    expired_at = fields.DateTime(required=True)
    created_at = fields.DateTime(required=True)
    created_by_id = fields.Int(required=True)


class ResetPasswordRequestSchema(Schema):
    email = fields.Email(required=True)


class ResetPasswordResponseSchema(Schema):
    user_id = fields.Int()
    email = fields.Email(required=True)
    token = fields.Str(required=True)


class ChangePasswordSchema(TwoPasswordsMixin, Schema):
    password_1 = fields.Str(required=True, validate=validate.Length(min=2, max=32))
    password_2 = fields.Str(required=True, validate=validate.Length(min=2, max=32))


class UserResponseSchema(Schema):
    id = fields.Int(required=True)
    email = fields.Email(required=True)
    is_active = fields.Bool(required=True)
    is_superuser = fields.Bool(required=True)

#
# class UserResponseSchema(SQLAlchemyAutoSchema):
#     class Meta:
#         model = User
#         load_instance = True
