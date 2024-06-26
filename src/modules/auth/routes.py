from starlette.routing import Route, Mount
from modules.auth import views

routes = [
    Mount(
        "/auth",
        routes=[
            Route("/me/", views.ProfileApiView),
            Route("/ips/", views.UserIPsRetrieveAPIView),
            Route("/ips/delete/", views.UserIPsDeleteAPIView),
            Route("/sign-in/", views.SignInAPIView),
            Route("/sign-up/", views.SignUpAPIView),
            Route("/sign-out/", views.SignOutAPIView),
            Route("/refresh-token/", views.RefreshTokenAPIView),
            Route("/invite-user/", views.InviteUserAPIView),
            Route("/reset-password/", views.ResetPasswordAPIView),
            Route("/change-password/", views.ChangePasswordAPIView),
            Route("/access-tokens/", views.UserAccessTokensLiceCreateAPIView),
            Route("/access-tokens/{token_id:int}/", views.UserAccessTokensDetailsAPIView),
        ],
    )
]
