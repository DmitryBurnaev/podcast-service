import os
import uuid
from hashlib import md5

import pytest

from common.enums import FileType
from core import settings
from modules.auth.models import UserIP
from modules.media.models import File
from modules.providers.utils import AudioMetaData
from tests.api.test_base import BaseTestAPIView
from tests.helpers import await_, create_file


class TestMediaFileAPIView(BaseTestAPIView):
    url = "/m/{token}/"
    user_ip = "172.17.0.2"

    def test_get_media_file__ok(self, client, image_file, user, mocked_s3):
        temp_link = f"https://s3.storage/tmp.link/{image_file.access_token}"
        mocked_s3.get_presigned_url.return_value = mocked_s3.async_return(temp_link)
        url = self.url.format(token=image_file.access_token)
        client.login(user)
        await_(UserIP.async_create(client.db_session, user_id=user.id, ip_address=self.user_ip))
        await_(client.db_session.commit())

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 200
        assert response.headers == image_file.headers

        response = client.get(url, headers={"X-Real-IP": self.user_ip}, allow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == temp_link

    def test_file_headers(self, dbs, image_file):
        await_(image_file.update(dbs, size=1024))
        await_(dbs.flush())
        assert image_file.headers == {"content-length": "1024", "content-type": "image/png"}

    def test_get_media_file_missed_ip__fail(self, client, image_file, user, mocked_s3):
        url = self.url.format(token=image_file.access_token)
        client.login(user)
        await_(UserIP.async_create(client.db_session, user_id=user.id, ip_address=self.user_ip))
        await_(client.db_session.commit())

        response = client.head(url)
        assert response.status_code == 404

        response = client.get(url, allow_redirects=False)
        assert response.status_code == 404

    def test_get_media_file_bad_token__fail(self, client, image_file, user, mocked_s3):
        url = self.url.format(token="fake-token")
        client.login(user)
        await_(UserIP.async_create(client.db_session, user_id=user.id, ip_address=self.user_ip))
        await_(client.db_session.commit())

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, allow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

    def test_get_media_file_not_found__fail(self, client, image_file, user, mocked_s3):
        url = self.url.format(token=image_file.access_token)
        client.login(user)

        await_(image_file.update(client.db_session, available=False))
        await_(UserIP.async_create(client.db_session, user_id=user.id, ip_address=self.user_ip))
        await_(client.db_session.commit())

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, allow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

    def test_get_image_file_not_allowed__fail(self, client, image_file, user, mocked_s3):
        url = self.url.format(token=image_file.access_token)
        client.login(user)

        await_(image_file.update(client.db_session, available=False, source_url=""))
        await_(UserIP.async_create(client.db_session, user_id=user.id, ip_address=self.user_ip))
        await_(client.db_session.commit())

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, allow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

    def test_get_public_image_file__ok(self, dbs, user, mocked_s3):
        source_url = f"https://test.source.url/{uuid.uuid4().hex}.jpg"
        image_file = await_(
            File.create(
                dbs,
                FileType.IMAGE,
                owner_id=user.id,
                source_url=source_url,
                public=True,
            )
        )
        await_(dbs.commit())

        await_(dbs.refresh(image_file))
        assert image_file.url == source_url

    def test_get_media_file_unknown_user_ip__fail(self, client, image_file, user, mocked_s3):
        url = self.url.format(token=image_file.access_token)
        client.login(user)

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, allow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

    def test_get_media_file_user_ip_rss_registered__fail(self, client, image_file, rss_file, user):
        url = self.url.format(token=image_file.access_token)
        client.login(user)
        await_(
            UserIP.async_create(
                client.db_session,
                user_id=user.id,
                ip_address=self.user_ip,
                registered_by=rss_file.access_token,
            )
        )
        await_(client.db_session.commit())

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 200
        assert response.headers == image_file.headers

        response = client.get(url, headers={"X-Real-IP": self.user_ip}, allow_redirects=False)
        assert response.status_code == 200
        assert response.headers == image_file.headers


class TestRSSFileAPIView(BaseTestAPIView):
    url = "/r/{token}/"
    user_ip = "172.17.0.2"
    temp_link = "https://s3.storage/tmp.link"

    @pytest.mark.parametrize(
        "method,status_code,headers",
        [
            ("head", 200, {"content-length": "1024", "content-type": "rss/xml"}),
            ("get", 302, {"location": temp_link}),
        ],
    )
    def test_get_rss__register_user_ip__ok(
        self, client, rss_file, user, mocked_s3, method, status_code, headers
    ):
        await_(rss_file.update(client.db_session, size=1024))
        await_(client.db_session.commit())

        mocked_s3.get_presigned_url.return_value = mocked_s3.async_return(self.temp_link)
        url = self.url.format(token=rss_file.access_token)
        client.login(user)

        response = client.request(method, url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == status_code
        assert response.headers == headers

        user_ip = await_(
            UserIP.async_get(client.db_session, user_id=user.id, ip_address=self.user_ip)
        )
        assert user_ip is not None
        assert user_ip.registered_by == rss_file.access_token

    def test_get_rss__user_ip_already_registered_by__with_current_rss__ok(
        self, client, rss_file, user, mocked_s3
    ):
        mocked_s3.get_presigned_url.return_value = mocked_s3.async_return(self.temp_link)

        await_(
            UserIP.async_create(
                client.db_session,
                user_id=user.id,
                ip_address=self.user_ip,
                registered_by=rss_file.access_token,
            )
        )
        await_(client.db_session.commit())

        url = self.url.format(token=rss_file.access_token)
        client.login(user)

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 200
        assert response.headers == rss_file.headers

        response = client.get(url, allow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 302
        assert response.headers["location"] == self.temp_link

    def test_get_rss__user_ip_already_registered_by__with_another_file__ok(
        self, client, rss_file, user, mocked_s3
    ):
        mocked_s3.get_presigned_url.return_value = mocked_s3.async_return(self.temp_link)
        await_(
            UserIP.async_create(
                client.db_session,
                user_id=user.id,
                ip_address=self.user_ip,
                registered_by=File.generate_token(),
            )
        )
        await_(client.db_session.commit())

        url = self.url.format(token=rss_file.access_token)
        client.login(user)

        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 200

        response = client.get(url, allow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 302
        assert response.headers["location"] == self.temp_link

    def test_get_not_rss__fail(self, client, image_file, user):
        client.login(user)
        url = self.url.format(token=image_file.access_token)
        response = client.head(url, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404

        response = client.get(url, allow_redirects=False, headers={"X-Real-IP": self.user_ip})
        assert response.status_code == 404


# TODO: Add tests
class TestFileURL:
    def test_public_url(self, image_file):
        ...

    def test_presigned_url(self):
        ...


class TestUploadAudioAPIView(BaseTestAPIView):
    url = "/api/media/upload/audio/"

    def test_upload__ok(
        self,
        client,
        user,
        mocked_s3,
            tmp_file,
        mocked_audio_metadata,
    ):
        audio_metadata = {
            "duration": 90,
            "author": "Test Author",
            "title": f"Test Title {uuid.uuid4().hex}",
            "album": f"Album #{uuid.uuid4().hex}",
            "track": "01",
        }
        remote_tmp_path = f"remote/tmp/{uuid.uuid4().hex}.mp3"

        mocked_audio_metadata.return_value = AudioMetaData(**audio_metadata)
        mocked_s3.upload_file_async.return_value = remote_tmp_path

        client.login(user)
        response = client.post(self.url, files={"file": tmp_file})
        response_data = self.assert_ok_response(response)
        result_hash = md5(
            str(
                {
                    "filename": os.path.basename(tmp_file.name),
                    "filesize": tmp_file.size,
                    "title": audio_metadata["title"],
                    "duration": audio_metadata["duration"],
                    "track": audio_metadata["track"],
                    "album": audio_metadata["album"],
                    "author": audio_metadata["author"],
                }
            ).encode()
        ).hexdigest()

        assert response_data["name"] == os.path.basename(tmp_file.name)
        assert response_data["meta"] == audio_metadata
        assert response_data["path"] == remote_tmp_path
        assert response_data["size"] == tmp_file.size
        assert response_data["hash"] == result_hash

        mocked_audio_metadata.assert_called()

    def test_upload__duplicate_uploaded_file__ok(
        self,
        user,
        client,
        tmp_file,
        mocked_s3,
        mocked_audio_metadata,
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
                    **audio_metadata
                }
            ).encode()
        ).hexdigest()

        mocked_audio_metadata.return_value = AudioMetaData(**audio_metadata)
        mocked_s3.get_file_size_async.return_value = tmp_file.size

        client.login(user)
        response = client.post(self.url, files={"file": tmp_file})
        response_data = self.assert_ok_response(response)
        remote_path = f"uploaded_audio_{result_hash}"

        assert response_data["name"] == os.path.basename(tmp_file.name)
        assert response_data["meta"] == audio_metadata
        assert response_data["path"] == os.path.join(settings.S3_BUCKET_TMP_AUDIO_PATH, remote_path)
        assert response_data["size"] == tmp_file.size
        assert response_data["hash"] == result_hash

        mocked_s3.upload_file_async.assert_not_awaited()
        mocked_audio_metadata.assert_called()

    def test_upload__empty_file__fail(self, client, user):
        client.login(user)
        response = client.post(self.url, files={"file": create_file(b"")})
        self.assert_bad_request(response, {"file": "result file-size is less than allowed"})

    def test_upload__too_big_file__fail(self, client, user):
        file = create_file(b"test-data-too-big" * 10)
        client.login(user)
        response = client.post(self.url, files={"file": file})
        self.assert_bad_request(response, {"file": "result file-size is more than allowed"})

    def test_upload__missed_file__fail(self, client, user):
        client.login(user)
        response = client.post(self.url, files={"fake": create_file(b"")})
        self.assert_bad_request(response, {
            "file": "Missing data for required field.",
            "fake": "Unknown field."
        })
