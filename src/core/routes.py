from starlette.routing import Mount, Route

from common.views import HealthCheckAPIView, SentryCheckAPIView
from modules.auth.routes import routes as auth_routes
from modules.podcast.routes import routes as podcast_routes
from modules.media.routes import routes as media_routes
from modules.media.routes import api_routes as api_media_routes

routes = [
    Mount("/api", routes=(auth_routes + podcast_routes + api_media_routes)),
    Route("/health_check/", HealthCheckAPIView),
    Route("/sentry_check/", SentryCheckAPIView),
    Mount("", routes=media_routes),
]
