from tests.api.test_base import BaseTestAPIView
from tests.helpers import await_


class TestAuthMeAPIView(BaseTestAPIView):
    url = "/api/auth/me/"

    def test_get__ok(self, client, user):
        client.login(user)
        response = client.get(self.url)
        response_data = self.assert_ok_response(response)
        assert response_data == {
            "id": user.id,
            "email": user.email,
            "is_active": True,
            "is_superuser": user.is_superuser,
        }

    def test_patch__ok(self, dbs, client, user):
        client.login(user)
        response = client.patch(self.url, json={"email": "new-user@test.com"})
        response_data = self.assert_ok_response(response)
        assert response_data == {
            "id": user.id,
            "email": "new-user@test.com",
            "is_active": True,
            "is_superuser": user.is_superuser,
        }

        await_(dbs.refresh(user))
        assert user.email == "new-user@test.com"
