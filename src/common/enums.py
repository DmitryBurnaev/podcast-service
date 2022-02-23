import enum


class SourceType(enum.Enum):
    YOUTUBE = "YOUTUBE"
    YANDEX = "YANDEX"
    UPLOAD = "UPLOAD"

    def __str__(self):
        return self.value


class EpisodeStatus(enum.Enum):
    NEW = "new"
    DOWNLOADING = "downloading"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    ERROR = "error"

    DL_PENDING = "pending"
    DL_EPISODE_DOWNLOADING = "episode_downloading"
    DL_EPISODE_POSTPROCESSING = "episode_postprocessing"
    DL_EPISODE_UPLOADING = "episode_uploading"
    DL_COVER_DOWNLOADING = "cover_downloading"
    DL_COVER_UPLOADING = "cover_uploading"

    def __str__(self):
        return self.value
