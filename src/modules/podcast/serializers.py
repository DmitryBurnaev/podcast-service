import datetime
from typing import Optional

from pydantic import BaseModel, constr

from common.serializers import ModelFromORM
from modules.podcast.models import Episode


class PodcastCreateModel(ModelFromORM):
    name: str
    description: Optional[str] = None


class PodcastUpdateModel(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    download_automatically: bool = True


class PodcastListModel(ModelFromORM):
    id: int
    name: str
    created_at: datetime.datetime
    image_url: Optional[str]


class PodcastDetailsModel(ModelFromORM):
    id: int
    name: str
    description: str
    created_at: datetime.datetime
    image_url: Optional[str]


class EpisodeCreateModel(ModelFromORM):
    youtube_link: str


class EpisodeUpdateModel(ModelFromORM):
    title: Optional[str] = ""
    description: constr()
    # description: Optional[str] = None
    author: constr()


class EpisodeListModel(ModelFromORM):
    id: int
    title: str
    created_at: datetime.datetime
    image_url: Optional[str]


class EpisodeDetailsModel(ModelFromORM):
    id: int
    title: str
    author: Optional[str]
    status: Episode.Status
    length: int
    watch_url: str
    remote_url: Optional[str]
    image_url: str
    file_size: Optional[int]
    description: Optional[str]
    created_at: datetime.datetime
    published_at: Optional[datetime.datetime]
