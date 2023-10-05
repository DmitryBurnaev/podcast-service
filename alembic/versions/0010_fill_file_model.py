"""Fill file model

Revision ID: 0010
Revises: 0009
Create Date: 2022-04-15 09:40:37.666183

"""
import datetime
from collections import defaultdict

from alembic import op
import sqlalchemy as sa


from sqlalchemy import table, column, select
from sqlalchemy.engine import Connection

from common.enums import EpisodeStatus, FileType
from modules.media.models import File  # only for `generate_token` method


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


podcasts = table(
    "podcast_podcasts",
    column("id", sa.Integer),
    column("image_url", sa.String),
    column("image_id", sa.Integer),
    column("owner_id", sa.Integer),
)

episodes = table(
    "podcast_episodes",
    column("id", sa.Integer),
    column("status", sa.String),
    column("remote_url", sa.String),
    column("image_url", sa.String),
    column("watch_url", sa.String),
    column("file_size", sa.String),
    column("owner_id", sa.Integer),
    column("image_id", sa.Integer),
    column("audio_id", sa.Integer),
)

files = table(
    "media_files",
    sa.Column("id", sa.Integer),
    sa.Column("type", sa.VARCHAR),
    sa.Column("path", sa.String),
    sa.Column("size", sa.Integer),
    sa.Column("source_url", sa.String),
    sa.Column("available", sa.Boolean),
    sa.Column("access_token", sa.String),
    sa.Column("owner_id", sa.Integer),
    sa.Column("created_at", sa.DateTime),
)


def _fill_media(conn: Connection, _table, items: list[dict]):
    _files_map = {}
    files_data = []
    for item in items:
        if item.get("audio_path"):
            audio = {
                "type": str(FileType.AUDIO),
                "path": item["audio_path"],
                "size": item["audio_size"],
                "available": True,
                "access_token": File.generate_token(),
                "owner_id": item["owner_id"],
                "created_at": datetime.datetime.utcnow(),
                "source_url": item["watch_url"],
            }
            _files_map[audio["access_token"]] = item["id"]
            files_data.append(audio)

        if item.get("image_path"):
            if item["image_path"].startswith("http"):
                image_path = ""
                image_url = item["image_path"]
            else:
                image_path = item["image_path"]
                image_url = ""

            image = {
                "type": str(FileType.IMAGE),
                "path": image_path,
                "source_url": image_url,
                "size": None,
                "available": True,
                "access_token": File.generate_token(),
                "owner_id": item["owner_id"],
                "created_at": datetime.datetime.utcnow(),
            }
            _files_map[image["access_token"]] = item["id"]
            files_data.append(image)

    op.bulk_insert(files, files_data)

    _file_data = defaultdict(dict)
    for row in conn.execute(select(files)):
        item = row._mapping  # noqa
        access_token = item["access_token"]
        if instance_id := _files_map.get(access_token):
            if item["type"] == str(FileType.AUDIO):
                _file_data[instance_id].update({"audio_id": item["id"]})
            else:
                _file_data[instance_id].update({"image_id": item["id"]})

    for instance_id, files_values in _file_data.items():
        op.execute(_table.update().where(_table.c.id == instance_id).values(files_values))


def fill_episodes_media(conn: Connection):
    episodes_select = select(episodes).where(episodes.c.status == str(EpisodeStatus.PUBLISHED))
    episode_items = []

    for row in conn.execute(episodes_select):
        item = row._mapping  # noqa
        episode_items.append(
            {
                "id": item["id"],
                "watch_url": item["watch_url"],
                "audio_path": item["remote_url"],
                "audio_size": item["file_size"],
                "image_path": item["image_url"],
                "owner_id": item["owner_id"],
            }
        )

    _fill_media(conn, episodes, episode_items)


def fill_podcast_media(conn: Connection):
    podcast_items = []
    for podcast_row in conn.execute(select(podcasts).where(podcasts.c.image_url.is_not(None))):
        item = podcast_row._mapping  # noqa
        image_path = item["image_url"]
        if "podcast-media/images" in image_path:
            image_path = image_path[image_path.index("images") :]

        podcast_items.append(
            {
                "id": item["id"],
                "image_path": image_path,
                "owner_id": item["owner_id"],
            }
        )

    _fill_media(conn, podcasts, podcast_items)


def upgrade():
    conn = op.get_bind()
    fill_podcast_media(conn)
    fill_episodes_media(conn)


def downgrade():
    conn = op.get_bind()
    conn.execute(episodes.update().values({"image_id": None, "audio_id": None}))
    conn.execute(podcasts.update().values({"image_id": None}))
    conn.execute(files.delete())
