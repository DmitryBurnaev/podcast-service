from pydantic import Field

from common.serializers import Serializer

# TODO: normal validation rules


class SignInRequestSerializer(Serializer):
    email: str = Field(max_length=128, regex="^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    password: str = Field()


class SignUpRequestSerializer(Serializer):
    email: str = Field(max_length=128, regex="^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    password_1: str = Field(min_length=3, max_length=32)
    password_2: str = Field(min_length=3, max_length=32)
    invite_token: str = Field()


class RefreshTokenRequestSerializer(Serializer):
    refresh_token: str = Field()


class JWTResponse(Serializer):
    access_token: str
    refresh_token: str
