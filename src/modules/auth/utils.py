import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from jwt import InvalidTokenError

from core import settings
from common.request import PRequest
from common.utils import hash_string, utcnow
from modules.auth.models import UserIP
from modules.auth.constants import AuthTokenType

logger = logging.getLogger(__name__)


@dataclass
class TokenCollection:
    refresh_token: str
    refresh_token_expired_at: datetime
    access_token: str
    access_token_expired_at: datetime


def encode_jwt(
    payload: dict,
    token_type: AuthTokenType = AuthTokenType.ACCESS,
    expires_in: int = None,
) -> tuple[str, datetime]:
    """Allows to prepare JWT for auth engine"""

    if token_type == AuthTokenType.REFRESH:
        expires_in = settings.JWT_REFRESH_EXPIRES_IN
    else:
        expires_in = expires_in or settings.JWT_EXPIRES_IN

    expired_at = utcnow() + timedelta(seconds=expires_in)
    payload["exp"] = expired_at
    payload["exp_iso"] = expired_at.isoformat()
    payload["token_type"] = str(token_type).lower()
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expired_at


def decode_jwt(encoded_jwt: str) -> dict:
    """Allows to decode received JWT token to payload"""
    parts_count = len(encoded_jwt.split("."))
    if parts_count != 3:
        raise InvalidTokenError("Not enough segments")

    return jwt.decode(encoded_jwt, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def extract_ip_address(request: PRequest) -> str | None:
    """Find IP address from request Headers"""

    if ip_address := request.headers.get(settings.REQUEST_IP_HEADER):
        return ip_address

    if settings.APP_DEBUG:
        return settings.DEFAULT_REQUEST_USER_IP

    user_id = request.user.id if "user" in request.scope else "Unknown"
    logger.warning(
        "Not found ip-header (%s) for user: %s | headers: %s",
        settings.REQUEST_IP_HEADER,
        user_id,
        request.headers,
    )
    return None


async def register_ip(request: PRequest):
    """Allows registration new IP for requested user"""

    logger.debug(
        "Requested register IP from: user: %i | headers: %s", request.user.id, request.headers
    )
    if not (ip_address := extract_ip_address(request)):
        return

    user_ip_data = {"user_id": request.user.id, "hashed_address": hash_string(ip_address)}

    if await UserIP.async_get(request.db_session, **user_ip_data):
        logger.debug("Found UserIP record for: %s | ip: %s", user_ip_data, ip_address)
    else:
        await UserIP.async_create(request.db_session, **user_ip_data)
        logger.debug("Created NEW UserIP record for: %s | ip: %s", user_ip_data, ip_address)
