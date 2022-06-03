from typing import ClassVar

from starlette.responses import RedirectResponse, Response

from common.enums import FileType
from common.exceptions import AuthenticationFailedError, NotFoundError
from common.request import PRequest
from common.views import BaseHTTPEndpoint
from common.utils import get_logger
from modules.auth.models import UserIP
from modules.auth.utils import extract_ip_address
from modules.media.models import File

logger = get_logger(__name__)


class BaseFileRedirectApiView(BaseHTTPEndpoint):
    """Check access to file's via token (by requested IP address)"""

    file_type: ClassVar[FileType] = None
    auth_backend = None

    async def get(self, request):
        file, _ = await self._get_file(request)
        return RedirectResponse(await file.presigned_url, status_code=302)

    async def head(self, request):
        file, _ = await self._get_file(request)
        return Response(headers=file.headers)

    async def _get_file(self, request: PRequest) -> tuple[File, UserIP]:
        access_token = request.path_params["access_token"]
        logger.debug("Finding file with access_token: %s", access_token)
        try:
            if not (ip_address := extract_ip_address(request)):
                raise AuthenticationFailedError("IP address not found in headers")

            if not File.token_is_correct(access_token):
                raise AuthenticationFailedError("Access token is invalid")

            filter_kwargs = {
                "access_token": access_token,
                "available": True,
            }
            if self.file_type:
                filter_kwargs["type"] = self.file_type

            logger.debug("Finding file for filters: %s", filter_kwargs)
            file = await File.async_get(self.db_session, **filter_kwargs)
            if not file:
                raise NotFoundError("File not found")

            user_ip = await self._check_ip_address(ip_address, file)

        except Exception as e:
            logger.exception("Couldn't allow access token to fetch file: %r", e)
            raise NotFoundError("File not found")

        return file, user_ip

    async def _check_ip_address(self, ip_address: str, file: File) -> UserIP:
        # TODO: can we check that logged-in user has superuser privileges?
        allowed_ips = {
            user_ip.ip_address: user_ip
            for user_ip in await UserIP.async_filter(self.db_session, user_id=file.owner_id)
        }
        if not (user_ip := allowed_ips.get(ip_address)):
            logger.warning("Unknown user's IP: %s | allowed: %s", ip_address, allowed_ips)
            raise AuthenticationFailedError(f"Invalid IP address: {ip_address}")

        return user_ip


class MediaFileRedirectAPIView(BaseFileRedirectApiView):
    async def get(self, request):
        file, user_ip = await self._get_file(request)
        if user_ip.registered_by != "":
            return Response(headers=file.headers)

        return RedirectResponse(await file.presigned_url, status_code=302)


class RSSRedirectAPIView(BaseFileRedirectApiView):
    """RSS endpoint (register IP for new fetching)"""

    file_type = FileType.RSS

    async def _get_file(self, request: PRequest) -> tuple[File, UserIP]:
        file, user_ip = await super()._get_file(request)
        if user_ip.registered_by and user_ip.registered_by != file.access_token:
            raise NotFoundError()

        return file, user_ip

    async def _check_ip_address(self, ip_address: str, file: File) -> UserIP:
        try:
            return await super()._check_ip_address(ip_address, file)
        except AuthenticationFailedError as e:
            if not await UserIP.async_get(self.db_session, registered_by=file.access_token):
                user_ip = await UserIP.async_create(
                    self.db_session,
                    user_id=file.owner_id,
                    ip_address=ip_address,
                    registered_by=file.access_token,
                )
                return user_ip

            raise e
