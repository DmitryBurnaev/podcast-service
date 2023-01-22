import enum
from typing import ClassVar


class StringEnum(enum.StrEnum):
    __enum_name__: ClassVar[str] = NotImplemented

    @classmethod
    def members(cls) -> list[str]:
        return list(cls.__members__.keys())


class SourceType(StringEnum):
    __enum_name__: ClassVar[str] = "source_type"

    YOUTUBE = "YOUTUBE"
    YANDEX = "YANDEX"
    UPLOAD = "UPLOAD"


class EpisodeStatus(StringEnum):
    __enum_name__: ClassVar[str] = "episode_status"

    NEW = "NEW"
    DOWNLOADING = "DOWNLOADING"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"

    # sub-statuses for DOWNLOADING (that statuses are not written to the DB, just for progress):
    DL_PENDING = "DL_PENDING"
    DL_EPISODE_DOWNLOADING = "DL_EPISODE_DOWNLOADING"
    DL_EPISODE_POSTPROCESSING = "DL_EPISODE_POSTPROCESSING"
    DL_EPISODE_UPLOADING = "DL_EPISODE_UPLOADING"
    DL_COVER_DOWNLOADING = "DL_COVER_DOWNLOADING"
    DL_COVER_UPLOADING = "DL_COVER_UPLOADING"

    @classmethod
    def members(cls) -> list[str]:
        return [status for status in super().members() if not status.startswith("DL_")]


class FileType(StringEnum):
    __enum_name__: ClassVar[str] = "file_type"

    AUDIO = "AUDIO"
    IMAGE = "IMAGE"
    RSS = "RSS"
