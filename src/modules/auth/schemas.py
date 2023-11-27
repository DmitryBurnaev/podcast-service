import typing
from marshmallow import Schema, ValidationError
from webargs import fields, validate


__all__ = [
    "SignInSchema",
    "SignUpSchema",
    "JWTResponseSchema",
    "UserResponseSchema",
    "RefreshTokenSchema",
    "ChangePasswordSchema",
    "UserPatchRequestSchema",
    "UserInviteRequestSchema",
    "UserInviteResponseSchema",
    "ResetPasswordRequestSchema",
    "ResetPasswordResponseSchema",
    "UserIPsResponseSchema",
    "UserIPsDeleteRequestSchema",
]


class TwoPasswordsMixin:
    PASSWORDS_REQUIRED = True
    PASSWORDS_MIN_LEN = 6
    PASSWORDS_MAX_LEN = 32

    password_1 = fields.Str(validate=validate.Length(max=PASSWORDS_MAX_LEN), allow_none=True)
    password_2 = fields.Str(validate=validate.Length(max=PASSWORDS_MAX_LEN), allow_none=True)

    def is_valid(self, data: typing.Mapping) -> typing.Mapping:
        errors, err_message = {}, ""
        for field in ("password_1", "password_2"):
            password = data.get(field)
            if password and len(password) < self.PASSWORDS_MIN_LEN:
                err_message = "Password's length is not enough"
                errors[field] = f"Passwords len must be at least {self.PASSWORDS_MIN_LEN} symbols"
            elif not password and self.PASSWORDS_REQUIRED:
                err_message = "Password is required"
                errors[field] = err_message

        if errors:
            raise ValidationError(err_message, data=errors)

        if data.get("password_1") != data.get("password_2"):
            msg = "Passwords must be equal"
            raise ValidationError(msg, data={"password_1": msg, "password_2": msg})

        return data


class SignInSchema(Schema):
    email = fields.Email(required=True)
    password = fields.Str(required=True, validate=validate.Length(min=2, max=32))


class SignUpSchema(TwoPasswordsMixin, Schema):
    email = fields.Email(required=True, validate=validate.Length(max=128))
    invite_token = fields.Str(required=True, validate=validate.Length(min=10, max=32))


class RefreshTokenSchema(Schema):
    refresh_token = fields.Str(required=True, validate=validate.Length(min=10, max=512))


class JWTResponseSchema(Schema):
    access_token = fields.Str(required=True)
    refresh_token = fields.Str(required=True)


class UserInviteRequestSchema(Schema):
    email = fields.Email(required=True)


class UserInviteResponseSchema(Schema):
    id = fields.Int()
    email = fields.Email(required=True)
    token = fields.Str(required=True)
    expired_at = fields.DateTime(required=True)
    created_at = fields.DateTime(required=True)
    owner_id = fields.Int(required=True)


class ResetPasswordRequestSchema(Schema):
    email = fields.Email(required=True)


class ResetPasswordResponseSchema(Schema):
    user_id = fields.Int()
    email = fields.Email(required=True)
    token = fields.Str(required=True)


class ChangePasswordSchema(TwoPasswordsMixin, Schema):
    token = fields.Str(required=True, validate=validate.Length(min=1))


class UserResponseSchema(Schema):
    id = fields.Int(required=True)
    email = fields.Email(required=True)
    is_active = fields.Bool(required=True)
    is_superuser = fields.Bool(required=True)


class UserPatchRequestSchema(TwoPasswordsMixin, Schema):
    PASSWORDS_REQUIRED = False  # password is not required for user's patch logic

    email = fields.Email()


class PodcastShortSchema(Schema):
    id = fields.Int()
    name = fields.String()


class UserIPsResponseSchema(Schema):
    id = fields.Int()
    hashed_address = fields.String()
    created_at = fields.DateTime()
    by_rss_podcast = fields.Nested(PodcastShortSchema)


class UserIPsDeleteRequestSchema(Schema):
    ids = fields.List(fields.Integer)
