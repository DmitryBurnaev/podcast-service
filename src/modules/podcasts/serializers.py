import datetime
from typing import Optional

from pydantic import BaseModel

from common.serializers import ModelFromORM


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
    safe_image_url: Optional[str]


class PodcastDetailsModel(ModelFromORM):
    id: int
    name: str
    description: str
    created_at: datetime.datetime
    image_url: Optional[str]
