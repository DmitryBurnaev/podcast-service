from starlette.routing import Route
from modules.podcast import views

routes = [
    Route("/podcasts/", views.PodcastListCreateAPIView),
    Route("/podcasts/{podcast_id:int}/", views.PodcastRUDAPIView),
    Route("/podcasts/{podcast_id:int}/episodes/", views.EpisodeListCreateAPIView),
    Route("/podcasts/{podcast_id:int}/episodes/{episode_id:int}/", views.EpisodeRUDAPIView),
]
