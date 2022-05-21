from starlette.routing import Route
from modules.media import views

routes = [
    Route("/m/{access_token:str}/", views.FileRedirectApiView),
    Route("/r/{access_token:str}/", views.RSSRedirectAPIView),
]
