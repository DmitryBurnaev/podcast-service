import datetime
from typing import Optional

from pydantic import BaseModel

from common.serializers import ModelFromORM


class PodcastCreateModel(BaseModel):
    name: str


class PodcastUpdateModel(BaseModel):
    name: str
    description: str


class PodcastListModel(ModelFromORM):
    id: int
    name: str
    created_at: datetime.datetime


class PodcastDetailsModel(ModelFromORM):
    id: int
    name: str
    created_at: datetime.datetime
    image_url: Optional[str]
