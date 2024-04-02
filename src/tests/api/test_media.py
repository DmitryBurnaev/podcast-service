import os
import uuid
from hashlib import md5
from unittest.mock import patch, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import FileType
from common.exceptions import NotSupportedError
from common.utils import hash_string
from core import settings
from modules.auth.models import UserIP, User
from modules.media.models import File
from modules.providers.utils import AudioMetaData
from tests.api.test_base import BaseTestAPIView
from tests.helpers import create_file, PodcastTestClient
from tests.mocks import MockS3Client

pytestmark = pytest.mark.asyncio


class TestMediaFileAPIView(BaseTestAPIView):
    url = "/m/{token}/"
    user_ip = "172.17.0.2"
    hashed_user_ip = hash_string("172.17.0.2")

    async def test_get_media_file__ok(
        self,
        client: PodcastTestClient,
        image_file: File,
        user: User,
        mocked_s3: MockS3Client,
    ):
        temp_link = f"https://s3.storage/tmp.link/{image_file.access_token}"
        mocked_s3.get_presigned_url.return_value = temp_link
        url = self.url.format(token=image_file.access_token)
        await client.login(user)
        await UserIP.async_create(
            client.db_session, user_id=user.id, hashed_address=self.hashed_user_ip
        )
        await client.db_session.commit()

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 200
        assert response.headers == image_file.headers

        response = client.get(url, headers={"X-Real-IP": self.user_ip}, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == temp_link

    async def test_file_headers(self, dbs: AsyncSession, image_file: File):
        await image_file.update(dbs, size=1024)
        await dbs.flush()
        assert image_file.headers == {"content-length": "1024", "content-type": "image/png"}

    @patch("core.settings.APP_DEBUG", False)
    async def test_get_media_file_missed_ip__fail(
        self,
        client: PodcastTestClient,
        image_file: File,
        user: User,
        mocked_s3: MockS3Client,
    ):
        url = self.url.format(token=image_file.access_token)
        await client.login(user)
        await UserIP.async_create(
            client.db_session, user_id=user.id, hashed_address=self.hashed_user_ip
        )
        await client.db_session.commit()

        response = client.head(url)
        assert response.status_code == 404

        response = client.get(url, follow_redirects=False)
        assert response.status_code == 404

    async def test_get_media_file_bad_token__fail(
        self,
        client: PodcastTestClient,
        user: User,
        mocked_s3: MockS3Client,
    ):
        url = self.url.format(token="fake-token")
        await client.login(user)
        await UserIP.async_create(
            client.db_session, user_id=user.id, hashed_address=self.hashed_user_ip
        )
        await client.db_session.commit()

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, follow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

    async def test_get_media_file_not_found__fail(
        self,
        client: PodcastTestClient,
        image_file: File,
        user: User,
        mocked_s3: MockS3Client,
    ):
        url = self.url.format(token=image_file.access_token)
        await client.login(user)

        await image_file.update(client.db_session, available=False)
        await UserIP.async_create(
            client.db_session, user_id=user.id, hashed_address=self.hashed_user_ip
        )
        await client.db_session.commit()

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, follow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

    async def test_get_image_file_not_allowed__fail(
        self,
        client: PodcastTestClient,
        image_file: File,
        user: User,
        mocked_s3: MockS3Client,
    ):
        url = self.url.format(token=image_file.access_token)
        await client.login(user)

        await image_file.update(client.db_session, available=False, source_url="")
        await UserIP.async_create(
            client.db_session, user_id=user.id, hashed_address=self.hashed_user_ip
        )
        await client.db_session.commit()

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, follow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

    async def test_get_public_image_file__ok(
        self,
        dbs: AsyncSession,
        user: User,
        mocked_s3: MockS3Client,
    ):
        source_url = f"https://test.source.url/{uuid.uuid4().hex}.jpg"
        image_file = await File.create(
            dbs,
            FileType.IMAGE,
            owner_id=user.id,
            source_url=source_url,
            public=True,
        )
        await dbs.commit()

        await dbs.refresh(image_file)
        assert image_file.url == source_url

    async def test_get_media_file_unknown_user_ip__fail(
        self,
        client: PodcastTestClient,
        image_file: File,
        user: User,
        mocked_s3: MockS3Client,
    ):
        url = self.url.format(token=image_file.access_token)
        await client.login(user)

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, follow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

    async def test_get_media_file_user_ip_rss_registered__fail(
        self,
        client: PodcastTestClient,
        image_file: File,
        rss_file: File,
        user: User,
    ):
        url = self.url.format(token=image_file.access_token)
        await client.login(user)
        await UserIP.async_create(
            client.db_session,
            user_id=user.id,
            hashed_address=self.hashed_user_ip,
            registered_by=rss_file.access_token,
            db_commit=True,
        )

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 200
        assert response.headers == image_file.headers

        response = client.get(url, headers={"X-Real-IP": self.user_ip}, follow_redirects=False)
        assert response.status_code == 200
        assert response.headers == {"content-length": "2"}


class TestRSSFileAPIView(BaseTestAPIView):
    url = "/r/{token}/"
    user_ip = "172.17.0.2"
    hashed_user_ip = hash_string("172.17.0.2")
    temp_link = "https://s3.storage/tmp.link"

    @pytest.mark.parametrize(
        "method,status_code,headers",
        [
            ("head", 200, {"content-length": "1024", "content-type": "rss/xml"}),
            ("get", 302, {"content-length": "0", "location": temp_link}),
        ],
    )
    async def test_get_rss__register_user_ip__ok(
        self,
        client: PodcastTestClient,
        rss_file: File,
        user: User,
        mocked_s3: MockS3Client,
        method: str,
        status_code: int,
        headers: dict,
    ):
        await rss_file.update(client.db_session, size=1024, db_commit=True)

        mocked_s3.get_presigned_url.return_value = self.temp_link
        url = self.url.format(token=rss_file.access_token)
        await client.login(user)

        response = client.request(
            method, url, headers={"X-Real-IP": self.user_ip}, follow_redirects=False
        )
        assert response.status_code == status_code
        assert response.headers == headers

        user_ip = await UserIP.async_get(
            client.db_session, user_id=user.id, hashed_address=self.hashed_user_ip
        )
        assert user_ip is not None
        assert user_ip.registered_by == rss_file.access_token

    async def test_get_rss__user_ip_already_registered_by__with_current_rss__ok(
        self,
        client: PodcastTestClient,
        rss_file: File,
        user: User,
        mocked_s3: MockS3Client,
    ):
        mocked_s3.get_presigned_url.return_value = self.temp_link

        await UserIP.async_create(
            client.db_session,
            user_id=user.id,
            hashed_address=self.hashed_user_ip,
            registered_by=rss_file.access_token,
            db_commit=True,
        )

        url = self.url.format(token=rss_file.access_token)
        await client.login(user)

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 200
        assert response.headers == rss_file.headers

        response = client.get(url, follow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 302
        assert response.headers["location"] == self.temp_link

    async def test_get_rss__user_ip_already_registered_by__with_another_file__ok(
        self,
        client: PodcastTestClient,
        rss_file: File,
        user: User,
        mocked_s3: MockS3Client,
    ):
        mocked_s3.get_presigned_url.return_value = self.temp_link
        await UserIP.async_create(
            client.db_session,
            user_id=user.id,
            hashed_address=self.hashed_user_ip,
            registered_by=File.generate_token(),
            db_commit=True,
        )

        url = self.url.format(token=rss_file.access_token)
        await client.login(user)

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 200

        response = client.get(url, follow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 302
        assert response.headers["location"] == self.temp_link

    async def test_get_not_rss__fail(self, client: PodcastTestClient, image_file: File, user: User):
        await client.login(user)
        url = self.url.format(token=image_file.access_token)
        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, follow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404


@patch("core.settings.S3_BUCKET_NAME", "test-bucket")
@patch("core.settings.S3_STORAGE_URL", "https://storage.test.url")
@patch("core.settings.SERVICE_URL", "https://self-service.test.url")
class TestFileURL:
    test_access_token = uuid.uuid4().hex

    @pytest.mark.parametrize(
        "file_type,url_path_pattern",
        (
            (FileType.RSS, "/r/{access_token}/"),
            (FileType.IMAGE, "/m/{access_token}/"),
            (FileType.AUDIO, "/m/{access_token}/"),
        ),
    )
    async def test_url(
        self,
        dbs: AsyncSession,
        user: User,
        file_type: FileType,
        url_path_pattern: str,
    ):
        file = await File.create(
            dbs,
            file_type=file_type,
            owner_id=user.id,
            path="/remote/path/to/file",
            db_commit=True,
        )
        url_path = url_path_pattern.format(access_token=file.access_token)
        assert file.url == f"https://self-service.test.url{url_path}"

    async def test_url__file_not_available(self, dbs: AsyncSession, image_file: File):
        await image_file.update(dbs, available=False, db_commit=True)
        assert image_file.url is None

    async def test_public_url(self, dbs: AsyncSession, image_file: File):
        await image_file.update(dbs, public=True, db_commit=True)
        assert image_file.url == f"https://storage.test.url/test-bucket{image_file.path}"

    async def test_public_url__from_source(self, dbs: AsyncSession, image_file: File):
        await image_file.update(
            dbs, public=True, source_url="https://test.file-src.com", db_commit=True
        )
        assert image_file.url == "https://test.file-src.com"

    async def test_presigned_url(self, mocked_s3: MockS3Client, image_file: File):
        mocked_url = f"https://storage.test.url/presigned-url-to-file/{image_file.id}"
        mocked_s3.get_presigned_url.return_value = mocked_url
        assert await image_file.presigned_url == mocked_url

    async def test_presigned_url__file_has_not_path(
        self,
        dbs: AsyncSession,
        mocked_s3: MockS3Client,
        image_file: File,
    ):
        await image_file.update(dbs, path="", db_commit=True)
        mocked_url = f"https://storage.test.url/presigned-url-to-file/{image_file.id}"
        mocked_s3.get_presigned_url.return_value = mocked_url
        with pytest.raises(NotSupportedError) as err:
            assert await image_file.presigned_url == mocked_url

        assert err.value.args == (f"Remote file {image_file} available but has not remote path.",)


class TestUploadAudioAPIView(BaseTestAPIView):
    url = "/api/media/upload/audio/"

    @pytest.mark.parametrize("metadata", ("full", "empty"))
    async def test_upload__ok(
        self,
        metadata: str,
        client: PodcastTestClient,
        user: User,
        mocked_s3: MockS3Client,
        tmp_file: File,
        mocked_audio_metadata: Mock,
    ):
        if metadata == "full":
            audio_metadata = {
                "duration": 90,
                "author": "Test Author",
                "title": f"Test Title {uuid.uuid4().hex}",
                "album": f"Album #{uuid.uuid4().hex}",
                "track": "01",
            }
        else:
            audio_metadata = {}

        remote_tmp_path = f"remote/tmp/{uuid.uuid4().hex}.mp3"

        mocked_audio_metadata.return_value = AudioMetaData(**audio_metadata)
        mocked_s3.upload_file_async.return_value = remote_tmp_path

        await client.login(user)
        file = (os.path.basename(tmp_file.name), tmp_file, "audio/mpeg")
        response = client.post(self.url, files={"file": file})
        response_data = self.assert_ok_response(response)
        result_hash = md5(
            str(
                {
                    "filename": os.path.basename(tmp_file.name),
                    "filesize": tmp_file.size,
                    "title": audio_metadata.get("title"),
                    "duration": audio_metadata.get("duration"),
                    "track": audio_metadata.get("track"),
                    "album": audio_metadata.get("album"),
                    "author": audio_metadata.get("author"),
                }
            ).encode()
        ).hexdigest()

        assert response_data["name"] == os.path.basename(tmp_file.name)
        assert response_data["meta"] == {
            "title": audio_metadata.get("title"),
            "duration": audio_metadata.get("duration"),
            "track": audio_metadata.get("track"),
            "album": audio_metadata.get("album"),
            "author": audio_metadata.get("author"),
        }
        assert response_data["path"] == remote_tmp_path
        assert response_data["size"] == tmp_file.size
        assert response_data["hash"] == result_hash

        mocked_audio_metadata.assert_called()

    async def test_upload__duplicate_uploaded_file__ok(
        self,
        user: User,
        client: PodcastTestClient,
        tmp_file: File,
        mocked_s3: MockS3Client,
        mocked_audio_metadata: Mock,
    ):
        audio_metadata = {
            "title": f"Test Title {uuid.uuid4().hex}",
            "duration": 90,
            "track": None,
            "album": None,
            "author": None,
        }
        result_hash = md5(
            str(
                {
                    "filename": os.path.basename(tmp_file.name),
                    "filesize": tmp_file.size,
                    **audio_metadata,
                }
            ).encode()
        ).hexdigest()

        mocked_audio_metadata.return_value = AudioMetaData(**audio_metadata)
        mocked_s3.get_file_size_async.return_value = tmp_file.size

        await client.login(user)
        file = (os.path.basename(tmp_file.name), tmp_file, "audio/mpeg")
        response = client.post(self.url, files={"file": file})
        response_data = self.assert_ok_response(response)
        remote_path = f"uploaded_{result_hash}"

        assert response_data["name"] == os.path.basename(tmp_file.name)
        assert response_data["meta"] == audio_metadata
        assert response_data["path"] == os.path.join(settings.S3_BUCKET_TMP_AUDIO_PATH, remote_path)
        assert response_data["size"] == tmp_file.size
        assert response_data["hash"] == result_hash

        mocked_s3.upload_file_async.assert_not_awaited()
        mocked_audio_metadata.assert_called()

    async def test_upload__empty_file__fail(self, client: PodcastTestClient, user: User):
        await client.login(user)
        file = ("test-audio.mp3", create_file(b""), "audio/mpeg")
        response = client.post(self.url, files={"file": file})
        self.assert_bad_request(response, {"file": "result file-size is less than allowed"})

    async def test_upload__too_big_file__fail(self, client: PodcastTestClient, user: User):
        await client.login(user)
        file = ("test-audio.mp3", create_file(b"test-data-too-big" * 10), "audio/mpeg")
        response = client.post(self.url, files={"file": file})
        self.assert_bad_request(response, {"file": "result file-size is more than allowed"})

    async def test_upload__incorrect_content_type__fail(
        self,
        client: PodcastTestClient,
        user: User,
    ):
        await client.login(user)
        file = ("test-audio.mp3", create_file(b"test-data"), "image/jpeg")
        response = client.post(self.url, files={"file": file})
        self.assert_bad_request(response, {"file": "File must be audio, not image/jpeg"})

    async def test_upload__missed_file__fail(self, client: PodcastTestClient, user: User):
        await client.login(user)
        response = client.post(self.url, files={"fake": create_file(b"")})
        self.assert_bad_request(
            response, {"file": "Missing data for required field.", "fake": "Unknown field."}
        )


class TestUploadImageAPIView(BaseTestAPIView):
    url = "/api/media/upload/image/"

    @staticmethod
    def _file_hash(file: File) -> str:
        return md5(
            str(
                {
                    "filename": os.path.basename(file.name),
                    "filesize": file.size,
                }
            ).encode()
        ).hexdigest()

    async def test_upload__ok(
        self,
        client: PodcastTestClient,
        user: User,
        mocked_s3: MockS3Client,
        tmp_file: File,
    ):

        remote_tmp_path = f"remote/tmp/{uuid.uuid4().hex}.png"
        presigned_url = f"https://s3.storage/link/{remote_tmp_path}/presigned_link/"
        mocked_s3.upload_file_async.return_value = remote_tmp_path
        mocked_s3.get_presigned_url.return_value = presigned_url

        await client.login(user)
        file = (os.path.basename(tmp_file.name), tmp_file, "image/png")
        response = client.post(self.url, files={"file": file})
        response_data = self.assert_ok_response(response)
        assert response_data == {
            "name": os.path.basename(tmp_file.name),
            "path": remote_tmp_path,
            "hash": self._file_hash(tmp_file),
            "size": tmp_file.size,
            "preview_url": presigned_url,
        }

    async def test_upload__duplicate_uploaded_file__ok(
        self,
        user: User,
        client: PodcastTestClient,
        tmp_file: File,
        mocked_s3: MockS3Client,
    ):
        result_hash = self._file_hash(tmp_file)
        mocked_s3.get_file_size_async.return_value = tmp_file.size

        await client.login(user)
        file = (os.path.basename(tmp_file.name), tmp_file, "image/png")
        response = client.post(self.url, files={"file": file})
        response_data = self.assert_ok_response(response)
        remote_path = f"uploaded_{result_hash}"

        assert response_data["name"] == os.path.basename(tmp_file.name)
        assert response_data["path"] == os.path.join(settings.S3_BUCKET_TMP_AUDIO_PATH, remote_path)
        assert response_data["size"] == tmp_file.size
        assert response_data["hash"] == result_hash

        mocked_s3.upload_file_async.assert_not_awaited()

    async def test_upload__empty_file__fail(self, client: PodcastTestClient, user: User):
        await client.login(user)
        file = ("test-image.png", create_file(b""), "image/png")
        response = client.post(self.url, files={"file": file})
        self.assert_bad_request(response, {"file": "result file-size is less than allowed"})

    async def test_upload__too_big_file__fail(self, client: PodcastTestClient, user: User):
        await client.login(user)
        file = ("test-image.png", create_file(b"test-data-too-big" * 10), "image/png")
        response = client.post(self.url, files={"file": file})
        self.assert_bad_request(response, {"file": "result file-size is more than allowed"})

    async def test_upload__incorrect_content_type__fail(
        self,
        client: PodcastTestClient,
        user: User,
    ):
        await client.login(user)
        file = ("test-image.png", create_file(b""), "audio/mpeg")
        response = client.post(self.url, files={"file": file})
        self.assert_bad_request(response, {"file": "File must be image, not audio/mpeg"})

    async def test_upload__missed_file__fail(self, client: PodcastTestClient, user: User):
        await client.login(user)
        response = client.post(self.url, files={"fake": create_file(b"")})
        self.assert_bad_request(
            response, {"file": "Missing data for required field.", "fake": "Unknown field."}
        )
