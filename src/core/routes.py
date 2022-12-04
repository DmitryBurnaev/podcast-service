from starlette.routing import Mount, Route
from starlette_web.tests.views import SentryCheckAPIView, HealthCheckAPIView

from modules.auth.routes import routes as auth_routes
from modules.podcast.routes import routes as podcast_routes, ws_routes as podcast_ws_routes
from modules.media.routes import routes as media_routes
from modules.media.routes import api_routes as api_media_routes

routes = [
    Mount("/api", routes=(auth_routes + podcast_routes + api_media_routes)),
    Route("/health_check/", HealthCheckAPIView),
    Route("/sentry_check/", SentryCheckAPIView),
    Mount("/ws", routes=podcast_ws_routes),
    Mount("", routes=media_routes),
]
