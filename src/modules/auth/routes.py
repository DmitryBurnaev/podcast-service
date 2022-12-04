from starlette_web.contrib.auth import views as starlette_auth_views

from starlette.routing import Route, Mount
from modules.auth import views

routes = [
    Mount(
        "/auth",
        routes=[
            Route("/me/", views.ProfileApiView),
            Route("/sign-in/", starlette_auth_views.SignInAPIView),
            Route("/sign-up/", starlette_auth_views.SignUpAPIView),
            Route("/sign-out/", starlette_auth_views.SignOutAPIView),
            Route("/refresh-token/", starlette_auth_views.RefreshTokenAPIView),
            Route("/invite-user/", starlette_auth_views.InviteUserAPIView),
            Route("/reset-password/", starlette_auth_views.ResetPasswordAPIView),
            Route("/change-password/", starlette_auth_views.ChangePasswordAPIView),
        ],
    )
]
