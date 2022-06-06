import pytest

from modules.auth.models import UserIP
from modules.media.models import File
from tests.api.test_base import BaseTestAPIView
from tests.helpers import await_


class TestMediaFileAPIView(BaseTestAPIView):
    url = "/m/{token}/"
    user_ip = "172.17.0.2"

    def test_get_media_file__ok(self, client, image_file, user, mocked_s3):
        temp_link = f"https://s3.storage/tmp.link/{image_file.access_token}"
        mocked_s3.get_file_url.return_value = mocked_s3.async_return(temp_link)
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

        mocked_s3.get_file_url.return_value = mocked_s3.async_return(self.temp_link)
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
        mocked_s3.get_file_url.return_value = mocked_s3.async_return(self.temp_link)

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
        mocked_s3.get_file_url.return_value = mocked_s3.async_return(self.temp_link)
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
