from starlette.routing import Route, Mount

from modules.auth.views import SignInAPIView, SignUpAPIView, SignOutAPIView, RefreshTokenAPIView

routes = [
    Mount('/auth', routes=[
        Route("/sign-in/", SignInAPIView),
        Route("/sign-up/", SignUpAPIView),
        Route("/sign-out/", SignOutAPIView),
        Route("/refresh-token/", RefreshTokenAPIView),
    ])
]
