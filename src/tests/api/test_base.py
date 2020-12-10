from typing import Union

from requests import Response

from common.models import BaseModel


class BaseTestCase:
    @staticmethod
    def assert_called_with(mock_callable, *args, **kwargs):
        """ Check mock object (callable) on call action with provided `args`, `kwargs` """

        assert mock_callable.called
        mock_call_args = mock_callable.call_args_list[-1]
        assert mock_call_args.args == args
        for key, value in kwargs.items():
            assert key in mock_call_args.kwargs, mock_call_args.kwargs
            assert mock_call_args.kwargs[key] == value


class BaseTestAPIView(BaseTestCase):
    url: str = NotImplemented

    @staticmethod
    def assert_bad_request(response: Response, error_details: dict):
        response_data = response.json()
        assert response.status_code == 400
        assert response_data["error"] == "Requested data is not valid."
        for error_field, error_value in error_details.items():
            assert error_field in response_data["details"]
            assert error_value in response_data["details"][error_field]

    @staticmethod
    def assert_not_found(response: Response, instance: BaseModel):
        assert response.status_code == 404
        assert response.json() == {
            "error": "Requested object not found.",
            "details": (
                f"{instance.__class__.__name__} #{instance.id} "
                f"does not exist or belongs to another user"
            ),
        }

    @staticmethod
    def assert_unauth(response: Response):
        assert response.status_code == 401
        assert response.json() == {
            "error": "Authentication is required.",
            "details": "Invalid token header. No credentials provided.",
        }

    @staticmethod
    def assert_auth_invalid(response: Union[Response, dict], details: str):
        if isinstance(response, Response):
            assert response.status_code == 401
            response = response.json()

        assert response == {
            "error": "Authentication credentials are invalid.",
            "details": details,
        }
