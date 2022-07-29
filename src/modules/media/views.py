import dataclasses
import os
import uuid
from contextlib import suppress
from hashlib import md5
from pathlib import Path
from typing import ClassVar

from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse, Response

from common.enums import FileType
from common.exceptions import (
    NotFoundError,
    S3UploadingError,
    InvalidParameterError,
    AuthenticationFailedError,
)
from common.request import PRequest
from common.storage import StorageS3
from common.views import BaseHTTPEndpoint
from common.utils import get_logger
from core import settings
from modules.auth.models import UserIP
from modules.auth.utils import extract_ip_address
from modules.media.models import File
from modules.media.schemas import FileUploadSchema, AudioFileResponseSchema
from modules.podcast.utils import save_uploaded_file, get_file_size
from modules.providers import utils as provider_utils
from modules.providers.utils import AudioMetaData

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
        logger.debug(
            "Finding UserIP with filters: ip_address %s | user_id %s", ip_address, file.owner_id
        )
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

    async def _check_ip_address(self, ip_address: str, file: File) -> UserIP:
        try:
            return await super()._check_ip_address(ip_address, file)
        except AuthenticationFailedError as e:
            logger.debug("Finding registrations for access token %s", file.access_token)
            if not await UserIP.async_get(self.db_session, registered_by=file.access_token):
                logger.debug(
                    "UserIPs not found. Create new: user_id %s | ip_address %s | registered_by %s",
                    file.owner_id,
                    ip_address,
                    file.access_token,
                )
                user_ip = await UserIP.async_create(
                    self.db_session,
                    user_id=file.owner_id,
                    ip_address=ip_address,
                    registered_by=file.access_token,
                )
                return user_ip

            raise e


class AudioFileUploadAPIView(BaseHTTPEndpoint):
    schema_request = FileUploadSchema
    schema_response = AudioFileResponseSchema
    max_title_length = 256

    @dataclasses.dataclass
    class UploadedFileData:
        filename: str
        filesize: int
        metadata: AudioMetaData

        @property
        def hash_str(self):
            data = self.__dict__ | self.metadata._asdict()  # noqa
            del data["metadata"]
            return md5(str(data).encode()).hexdigest()

        @property
        def tmp_filename(self):
            file_ext = os.path.splitext(self.filename)[-1]
            return f"uploaded_audio_{self.hash_str}{file_ext}"

    async def post(self, request):
        cleaned_data = await self._validate(request, location="form")
        tmp_path, filename = await self._save_audio(cleaned_data["file"])
        uploaded_file = self.UploadedFileData(
            filename=filename,
            filesize=get_file_size(tmp_path),
            metadata=provider_utils.audio_metadata(tmp_path),
        )
        new_tmp_path = settings.TMP_AUDIO_PATH / uploaded_file.tmp_filename
        os.rename(tmp_path, new_tmp_path)
        remote_path = await self._upload_to_storage(uploaded_file, new_tmp_path)

        with suppress(FileNotFoundError):
            os.remove(new_tmp_path)

        return self._response(
            {
                "name": filename,
                "path": remote_path,
                "meta": uploaded_file.metadata,
                "size": uploaded_file.filesize,
                "hash": uploaded_file.hash_str,
            }
        )

    @staticmethod
    async def _upload_to_storage(uploaded_file: UploadedFileData, tmp_path: Path) -> str:
        storage = StorageS3()
        tmp_filename = os.path.basename(tmp_path)

        remote_path = os.path.join(settings.S3_BUCKET_TMP_AUDIO_PATH, tmp_filename)
        if remote_file_size := await storage.get_file_size_async(dst_path=remote_path):
            if remote_file_size == get_file_size(tmp_path):
                logger.info(
                    'File "%s" already uploaded to s3, and have correct size: '
                    "tmp_filename: %s | metadata: %s | remote_file_size: %i",
                    uploaded_file.filename,
                    tmp_filename,
                    uploaded_file.metadata,
                    remote_file_size,
                )
                return remote_path

            logger.warning(
                'File "%s" already uploaded to s3, but size not equal (rewrite it): '
                "tmp_filename: %s | metadata: %s | remote_file_size: %i",
                uploaded_file.filename,
                tmp_filename,
                uploaded_file.metadata,
                remote_file_size,
            )

        remote_path = await storage.upload_file_async(
            src_path=tmp_path, dst_path=settings.S3_BUCKET_TMP_AUDIO_PATH
        )
        if not remote_path:
            raise S3UploadingError("Couldn't upload audio file")

        return remote_path

    @staticmethod
    async def _save_audio(upload_file: UploadFile) -> tuple[Path, str]:
        try:
            tmp_path = await save_uploaded_file(
                uploaded_file=upload_file,
                prefix=f"uploaded_episode_{uuid.uuid4().hex}",
                max_file_size=settings.MAX_UPLOAD_AUDIO_FILESIZE,
                tmp_path=settings.TMP_AUDIO_PATH,
            )
        except ValueError as e:
            raise InvalidParameterError(details={"file": str(e)})

        return tmp_path, upload_file.filename
