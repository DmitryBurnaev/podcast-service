from starlette.routing import Route, Mount
from modules.auth import views

routes = [
    Mount('/auth', routes=[
        Route("/sign-in/", views.SignInAPIView),
        Route("/sign-up/", views.SignUpAPIView),
        Route("/sign-out/", views.SignOutAPIView),
        Route("/refresh-token/", views.RefreshTokenAPIView),
        Route("/invite-user/", views.InviteUserAPIView),
    ])
]
