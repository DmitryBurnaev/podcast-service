from starlette.routing import Route
from modules.media import views

routes = [
    Route("/m/{access_token:str}/", views.MediaFileRedirectAPIView),
    Route("/r/{access_token:str}/", views.RSSRedirectAPIView),
]

api_routes = [
    Route("/media/upload/audio/", views.AudioFileUploadAPIView),
]
