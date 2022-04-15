"""Fill file model

Revision ID: 2c92a9133aaa
Revises: 9e313cd15619
Create Date: 2022-04-15 09:40:37.666183

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
from sqlalchemy import table, column, String, Integer, select

revision = '2c92a9133aaa'
down_revision = '9e313cd15619'
branch_labels = None
depends_on = None


episodes = table(
    "podcast_episodes",
    column("id", sa.Integer),
    column("status", sa.String),
    column("remote_url", sa.String),
    column("image_url", sa.String),
    column("file_size", sa.String),
    column("owner_id", sa.Integer),
)

files = op.create_table(
    'media_files',
    sa.Column('id', sa.Integer),
    sa.Column('type', sa.VARCHAR),
    sa.Column('path', sa.String),
    sa.Column('size', sa.Integer),
    sa.Column('source_url', sa.String),
    sa.Column('available', sa.Boolean),
    sa.Column('access_token', sa.String),
    sa.Column('owner_id', sa.Integer),
    sa.Column('created_at', sa.DateTime),
)


def fill_media():
    episodes_select = select(episodes).where(episodes.c.status)
    episode_items = []
    for row in op.execute(episodes_select):
        episode_items.append({
            "id": row._mapping['id'],
            "audio_path": row._mapping['remote_url'],
            "audio_size": row._mapping['file_size'],
            "image_path": row._mapping['image_url'],
            "owner_id": row._mapping['owner_id'],
        })

    d = {
        "episode_id": 1,
        "audio_path": "",
        "audio_size": 12,
        "image_path": "",
        "owner_id": 1,
    }


def upgrade():
    pass


def downgrade():
    pass
