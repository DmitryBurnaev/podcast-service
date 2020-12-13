from starlette.routing import Mount, Route

from common.views import HealthCheckAPIView, SentryCheckAPIView
from modules.auth.routes import routes as auth_routes
from modules.podcast.routes import routes as podcast_routes

routes = [
    Mount("/api", routes=(auth_routes + podcast_routes)),
    Route("/health_check/", HealthCheckAPIView),
    Route("/sentry_check/", SentryCheckAPIView),
]
