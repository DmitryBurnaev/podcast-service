from datetime import datetime, timedelta
from typing import Tuple

from jose import jwt

from core import settings


def encode_jwt(payload, refresh=False, expires_in: int = None) -> Tuple[str, datetime]:
    """ Allows to prepare JWT for auth engine """

    now_time = datetime.utcnow()
    if refresh:
        expires_in = settings.JWT_REFRESH_EXPIRES_IN
        payload["token_type"] = "refresh"
    else:
        expires_in = expires_in or settings.JWT_EXPIRES_IN
        payload["token_type"] = "access"

    expired_at = now_time + timedelta(seconds=expires_in)
    payload["exp"] = expired_at
    payload["exp_iso"] = expired_at.isoformat()
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expired_at


def decode_jwt(encoded_jwt: str) -> dict:
    """ Allows to decode received JWT token to payload """

    return jwt.decode(
        encoded_jwt, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
