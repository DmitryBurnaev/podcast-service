import dataclasses
import os
import uuid
from contextlib import suppress
from hashlib import md5
from pathlib import Path
from typing import ClassVar

from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse, Response

from core import settings
from common.enums import FileType
from common.exceptions import (
    NotFoundError,
    S3UploadingError,
    InvalidRequestError,
    AuthenticationFailedError,
)
from common.request import PRequest
from common.storage import StorageS3
from common.views import BaseHTTPEndpoint
from common.utils import get_logger
from modules.media.models import File
from modules.auth.models import UserIP
from modules.auth.utils import extract_ip_address
from modules.media.schemas import AudioFileUploadSchema, AudioFileResponseSchema
from modules.podcast.utils import save_uploaded_file, get_file_size
from modules.providers import utils as provider_utils
from modules.providers.utils import AudioMetaData

logger = get_logger(__name__)


class BaseFileRedirectApiView(BaseHTTPEndpoint):
    """Check access to file's via token (by requested IP address)"""

    file_type: ClassVar[FileType] = None
    auth_backend = None

    async def get(self, request: PRequest) -> Response:
        file, _ = await self._get_file(request)
        return RedirectResponse(await file.presigned_url, status_code=302)

    async def head(self, request: PRequest) -> Response:
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

        except Exception as exc:
            logger.exception("Couldn't allow access token to fetch file: %r", exc)
            raise NotFoundError("File not found") from exc

        return file, user_ip

    async def _check_ip_address(self, ip_address: str, file: File) -> UserIP:
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
    async def get(self, request: PRequest) -> Response:
        file, user_ip = await self._get_file(request)
        if user_ip.registered_by != "":
            logger.debug(
                "Accessing to media resource %s from user's IP: %s | registered_by: %s",
                file,
                user_ip,
                user_ip.registered_by,
            )
            return Response("OK")

        return RedirectResponse(await file.presigned_url, status_code=302)


class RSSRedirectAPIView(BaseFileRedirectApiView):
    """RSS endpoint (register IP for new fetching)"""

    file_type = FileType.RSS

    async def _check_ip_address(self, ip_address: str, file: File) -> UserIP:
        try:
            return await super()._check_ip_address(ip_address, file)
        except AuthenticationFailedError as exc:
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

            raise exc


class AudioFileUploadAPIView(BaseHTTPEndpoint):
    schema_request = AudioFileUploadSchema
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.storage = StorageS3()

    async def post(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request, location="form")
        tmp_path, filename = await self._save_audio(cleaned_data["file"])
        uploaded_file = self.UploadedFileData(
            filename=filename,
            filesize=get_file_size(tmp_path),
            metadata=provider_utils.audio_metadata(tmp_path),
        )
        new_tmp_path = settings.TMP_AUDIO_PATH / uploaded_file.tmp_filename
        os.rename(tmp_path, new_tmp_path)

        cover_data = await self._audio_cover(new_tmp_path)
        remote_audio_path = await self._upload_file(
            local_path=new_tmp_path,
            remote_path=settings.S3_BUCKET_TMP_AUDIO_PATH,
            uploaded_file=uploaded_file,
        )
        with suppress(FileNotFoundError, TypeError):
            os.remove(new_tmp_path)

        return self._response(
            {
                "name": filename,
                "path": remote_audio_path,
                "meta": uploaded_file.metadata,
                "size": uploaded_file.filesize,
                "hash": uploaded_file.hash_str,
                "cover": cover_data,
            }
        )

    async def _upload_file(
        self, local_path: Path, remote_path: str, uploaded_file: UploadedFileData | None = None
    ) -> str:
        tmp_filename = os.path.basename(local_path)

        if remote_file_size := await self.storage.get_file_size_async(
            filename=tmp_filename, remote_path=remote_path
        ):
            if remote_file_size == get_file_size(local_path):
                logger.info(
                    "SKIP uploading: file already uploaded to s3 and have correct size: "
                    "tmp_filename: %s | remote_file_size: %i | uploaded_file: %s |",
                    tmp_filename,
                    remote_file_size,
                    uploaded_file,
                )
                return os.path.join(remote_path, tmp_filename)

            logger.warning(
                'File "%s" already uploaded to s3, but size not equal (will be rewritten): '
                "remote_file_size: %i | uploaded_file: %s |",
                tmp_filename,
                remote_file_size,
                uploaded_file,
            )

        remote_path = await self.storage.upload_file_async(local_path, remote_path)
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
        except ValueError as exc:
            raise InvalidRequestError(details={"file": str(exc)}) from exc

        return tmp_path, upload_file.filename

    async def _audio_cover(self, audio_path: Path) -> dict | None:
        if not (cover := provider_utils.audio_cover(audio_path)):
            return None

        remote_cover_path = await self._upload_file(
            local_path=cover.path,
            remote_path=settings.S3_BUCKET_IMAGES_PATH,
        )
        cover_data = {
            "hash": cover.hash,
            "size": cover.size,
            "path": remote_cover_path,
            "preview_url": await self.storage.get_presigned_url(remote_cover_path),
        }
        return cover_data
