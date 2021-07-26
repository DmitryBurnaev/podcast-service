from starlette.routing import Route
from modules.podcast import views

routes = [
    Route("/progress/", views.ProgressAPIView),
    Route("/playlist/", views.PlayListAPIView),
    Route("/episodes/", views.EpisodeListCreateAPIView),
    Route("/podcasts/", views.PodcastListCreateAPIView),
    Route("/podcasts/{podcast_id:int}/", views.PodcastRUDAPIView),
    Route("/podcasts/{podcast_id:int}/episodes/", views.EpisodeListCreateAPIView),
    Route("/podcasts/{podcast_id:int}/generate_rss/", views.PodcastGenerateRSSAPIView),
    Route("/episodes/{episode_id:int}/", views.EpisodeRUDAPIView),
    Route("/episodes/{episode_id:int}/download/", views.EpisodeDownloadAPIView),
]
