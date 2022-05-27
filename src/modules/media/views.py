from starlette.responses import RedirectResponse, Response

from common.exceptions import AuthenticationFailedError, NotFoundError
from common.request import PRequest
from common.views import BaseHTTPEndpoint
from common.utils import get_logger
from modules.auth.models import UserIP
from modules.auth.utils import extract_ip_address
from modules.media.models import File

logger = get_logger(__name__)


class FileRedirectApiView(BaseHTTPEndpoint):
    """Check access to file's via token (by requested IP address)"""

    async def get(self, request):
        file, user_has_ip = await self._get_file(request)
        if not user_has_ip:
            return Response(headers=file.headers)

        return RedirectResponse(await file.remote_url, status_code=302)

    async def head(self, request):
        file, _ = await self._get_file(request)
        return Response(headers=file.headers)

    async def _get_file(self, request: PRequest) -> tuple[File, bool]:
        access_token = request.path_params["access_token"]
        logger.debug("Finding file with access_token: %s", access_token)
        try:
            if not (ip_address := extract_ip_address(request)):
                raise AuthenticationFailedError("IP address not found in headers")

            if not File.token_is_correct(access_token):
                raise AuthenticationFailedError("Access token is invalid")

            if not (file := await File.async_get(self.db_session, access_token=access_token)):
                raise NotFoundError("File not found")

            user_has_ip = await self._check_ip_address(ip_address, file)

        except Exception as e:
            logger.exception("Couldn't allow access token to fetch file: %r", e)
            raise NotFoundError

        return file, user_has_ip

    async def _check_ip_address(self, ip_address: str, file: File) -> bool:
        # TODO: can we check that logged-in user has superuser privileges?
        allowed_ips = {
            user_ip.ip_address
            for user_ip in await UserIP.async_filter(self.db_session, user_id=file.owner_id)
        }
        if ip_address not in allowed_ips:
            logger.warning("Unknown user's IP: %s | allowed: %s", ip_address, allowed_ips)
            raise AuthenticationFailedError(f"Invalid IP address: {ip_address}")

        return True


class RSSRedirectAPIView(FileRedirectApiView):
    """RSS endpoint (register IP for new fetching)"""

    async def get(self, request):
        file, _ = await self._get_file(request)
        return RedirectResponse(await file.remote_url, status_code=302)

    async def _check_ip_address(self, ip_address: str, file: File):
        try:
            await super()._check_ip_address(ip_address, file)
        except AuthenticationFailedError as e:
            if not await UserIP.async_get(self.db_session, registed_by=file.access_token):
                await UserIP.async_create(
                    self.db_session,
                    user_id=file.owner_id,
                    ip_address=ip_address,
                    registed_by=file.access_token,
                )
                return False

            raise e
