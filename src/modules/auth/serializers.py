import datetime

from pydantic import Field, BaseModel


# TODO: normal validation rules
from common.serializers import ModelFromORM


class EmailField:
    max_length = 128
    regex = "^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

    def __call__(self, *args, **kwargs):
        return Field(max_length=self.max_length, regex=self.regex)


class SignInModel(BaseModel):
    email: str = EmailField()
    password: str = Field()


class SignUpModel(BaseModel):
    email: str = EmailField()
    password_1: str = Field(min_length=3, max_length=32)
    password_2: str = Field(min_length=3, max_length=32)
    invite_token: str = Field()


class RefreshTokenModel(BaseModel):
    refresh_token: str = Field()


class JWTResponseModel(BaseModel):
    access_token: str
    refresh_token: str


class UserInviteModel(BaseModel):
    email: str = EmailField()


class UserInviteResponseModel(ModelFromORM):
    email: str
    token: str
    expired_at: datetime.datetime
    created_at: datetime.datetime
    created_by_id: int
