from starlette.routing import Route, Mount

from modules.podcasts.views.podcasts import PodcastListCreateAPIView, PodcastRUDAPIView
from modules.auth.routes import routes as auth_routes

routes = [
    Mount('/api', routes=[
            Route("/podcasts/", PodcastListCreateAPIView),
            Route("/podcasts/{podcast_id:int}/", PodcastRUDAPIView),
        ] + auth_routes
    )
]

