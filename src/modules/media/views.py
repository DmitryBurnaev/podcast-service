import os
import uuid
import logging
from dataclasses import dataclass, asdict
from contextlib import suppress
from functools import cached_property
from hashlib import md5
from pathlib import Path
from typing import ClassVar

from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse, Response

from core import settings
from common.utils import hash_string
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
from modules.media.models import File
from modules.auth.models import UserIP
from modules.auth.utils import extract_ip_address
from modules.media.schemas import (
    AudioFileUploadSchema,
    AudioFileResponseSchema,
    ImageUploadedSchema,
    ImageFileUploadSchema,
)
from modules.podcast.utils import save_uploaded_file, get_file_size
from modules.providers import utils as provider_utils
from modules.providers.utils import AudioMetaData

logger = logging.getLogger(__name__)


@dataclass
class UploadedFileData:
    filename: str
    _local_path: Path
    filesize: int = 0
    local_path: Path | None = None
    remote_path: str | None = None
    metadata: AudioMetaData | None = None

    def __post_init__(self):
        self.filesize = get_file_size(self._local_path)
        new_path = settings.TMP_AUDIO_PATH / self.uploaded_name
        os.rename(self._local_path, new_path)
        self.local_path = new_path

    @cached_property
    def hash_str(self):
        data = {key: value for key, value in asdict(self).items() if key != "metadata"}
        if self.metadata:
            data |= self.metadata._as_dict()  # noqa

        return md5(str(data).encode()).hexdigest()

    @cached_property
    def uploaded_name(self):
        file_ext = os.path.splitext(self.filename)[-1]
        return f"uploaded_{self.hash_str}{file_ext}"


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
            logger.warning("Couldn't allow access token to fetch file: %r", exc)
            raise NotFoundError("File not found") from exc

        return file, user_ip

    async def _check_ip_address(self, ip_address: str, file: File) -> UserIP:
        logger.debug(
            "Finding UserIP with filters: ip_address %s | user_id %s", ip_address, file.owner_id
        )
        user_ip = await UserIP.async_get(
            self.db_session, user_id=file.owner_id, hashed_address=hash_string(ip_address)
        )
        if not user_ip:
            logger.warning("Unknown user's IP: %s | user_id: %i", ip_address, file.owner_id)
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
                    hashed_address=hash_string(ip_address),
                    registered_by=file.access_token,
                )
                return user_ip

            raise exc


class BaseUploadAPIView(BaseHTTPEndpoint):
    remote_path: ClassVar[str]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.storage = StorageS3()

    # async def _upload_file(self, uploaded_file: UploadedFileData) -> str:
    #     local_path = uploaded_file.tmp_local_path
    #     tmp_filename = os.path.basename(local_path)
    #
    #     if remote_file_size := await self.storage.get_file_size_async(
    #         filename=tmp_filename, remote_path=self.remote_path
    #     ):
    #         if remote_file_size == get_file_size(local_path):
    #             logger.info(
    #                 "SKIP uploading: file already uploaded to s3 and have correct size: "
    #                 "tmp_filename: %s | remote_file_size: %i | uploaded_file: %s |",
    #                 tmp_filename,
    #                 remote_file_size,
    #                 uploaded_file,
    #             )
    #             return os.path.join(self.remote_path, tmp_filename)
    #
    #         logger.warning(
    #             'File "%s" already uploaded to s3, but size not equal (will be rewritten): '
    #             "remote_file_size: %i | uploaded_file: %s |",
    #             tmp_filename,
    #             remote_file_size,
    #             uploaded_file,
    #         )
    #
    #     remote_path = await self.storage.upload_file_async(local_path, self.remote_path)
    #     if not remote_path:
    #         raise S3UploadingError("Couldn't upload audio file")
    #
    #     return remote_path

    async def _upload_file(self, file_path: Path, filename: str, remote_path: str | None = None) -> UploadedFileData:
        remote_path = remote_path or self.remote_path
        uploaded_file = UploadedFileData(filename=filename, _local_path=file_path)
        uploaded_file.remote_path = await self._perform_file_uploading(
            uploaded_file=uploaded_file, remote_path=remote_path
        )
        return uploaded_file

    async def _perform_file_uploading(self, uploaded_file: UploadedFileData, remote_path: str,) -> str:
        local_path = uploaded_file.local_path
        uploaded_filename = uploaded_file.uploaded_name

        if remote_file_size := await self.storage.get_file_size_async(
            filename=uploaded_filename, remote_path=self.remote_path
        ):
            if remote_file_size == get_file_size(local_path):
                logger.info(
                    "SKIP uploading: file already uploaded to s3 and have correct size: "
                    "tmp_filename: %s | remote_file_size: %i | uploaded_file: %s |",
                    uploaded_filename,
                    remote_file_size,
                    uploaded_file,
                )
                return os.path.join(remote_path, uploaded_filename)

            logger.warning(
                'File "%s" already uploaded to s3, but size not equal (will be rewritten): '
                "remote_file_size: %i | uploaded_file: %s |",
                uploaded_filename,
                remote_file_size,
                uploaded_file,
            )

        result_remote_path = await self.storage.upload_file_async(local_path, remote_path)
        if not result_remote_path:
            raise S3UploadingError("Couldn't upload file to S3")

        return result_remote_path

    @staticmethod
    def _clean(uploaded_file: UploadedFileData) -> None:
        with suppress(FileNotFoundError, TypeError):
            os.remove(uploaded_file.local_path)


class AudioFileUploadAPIView(BaseUploadAPIView):
    schema_request = AudioFileUploadSchema
    schema_response = AudioFileResponseSchema
    max_title_length = 256

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.storage = StorageS3()

    async def post(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request, location="form")
        tmp_path, filename = await self._save_audio(cleaned_data["file"])
        uploaded_file = await self._upload_file(tmp_path, filename)
        cover_data = await self._get_cover_data(uploaded_file.local_path)
        self._clean(uploaded_file)
        return self._response(
            {
                "name": filename,
                "path": uploaded_file.remote_path,
                "meta": uploaded_file.metadata,
                "size": uploaded_file.filesize,
                "hash": uploaded_file.hash_str,
                "cover": cover_data,
            }
        )

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

    async def _get_cover_data(self, audio_path: Path) -> dict | None:
        if not (cover := provider_utils.audio_cover(audio_path)):
            return None

        # TODO: recheck this logic too
        uploaded_file = await self._upload_file(
            local_path=cover.path,
            filename=cover.path.name,
            remote_path=settings.S3_BUCKET_IMAGES_PATH,
        )
        cover_data = {
            "hash": cover.hash,
            "size": cover.size,
            "path": uploaded_file.remote_path,
            "preview_url": await self.storage.get_presigned_url(uploaded_file.remote_path),
        }
        return cover_data


class ImageFileUploadAPIView(BaseUploadAPIView):
    """Upload image, save to s3 (can be useful for manual changing episode's cover)"""

    schema_request = ImageFileUploadSchema
    schema_response = ImageUploadedSchema

    async def post(self, request: PRequest) -> Response:
        cleaned_data = await self._validate(request, location="form")
        tmp_path, filename = await self._save_image(cleaned_data["file"])
        uploaded_file = await self._upload_file(tmp_path, filename)
        self._clean(uploaded_file)
        return self._response(
            {
                "name": filename,
                "path": uploaded_file.remote_path,
                "size": uploaded_file.filesize,
                "hash": uploaded_file.hash_str,
                "preview_url": await self.storage.get_presigned_url(uploaded_file.remote_path),
            }
        )

    @staticmethod
    async def _save_image(upload_file: UploadFile) -> tuple[Path, str]:
        try:
            tmp_path = await save_uploaded_file(
                uploaded_file=upload_file,
                prefix=f"episode_cover_{uuid.uuid4().hex}",
                max_file_size=settings.MAX_UPLOAD_IMAGE_FILESIZE,
                tmp_path=settings.TMP_IMAGE_PATH,
            )
        except ValueError as exc:
            raise InvalidRequestError(details={"file": str(exc)}) from exc

        return tmp_path, upload_file.filename
