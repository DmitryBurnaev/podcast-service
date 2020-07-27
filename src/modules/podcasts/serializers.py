import datetime
from typing import Optional

from common.serializers import Serializer, ModelSerializer


class PodcastCreateSerializer(Serializer):
    name: str


class PodcastListSerializer(ModelSerializer):
    id: int
    name: str
    created_at: datetime.datetime


class PodcastDetailsSerializer(ModelSerializer):
    id: int
    name: str
    created_at: datetime.datetime
    image_url: Optional[str]
