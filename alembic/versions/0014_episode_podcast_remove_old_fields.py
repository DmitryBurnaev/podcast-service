"""Episode+Podcast: remove old fields

Revision ID: 0014
Revises: 0013
Create Date: 2022-06-15 16:46:54.037564

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("podcast_episodes", "remote_url")
    op.drop_column("podcast_episodes", "image_url")
    op.drop_column("podcast_episodes", "file_size")
    op.drop_column("podcast_episodes", "file_name")
    op.drop_column("podcast_podcasts", "rss_link")
    op.drop_column("podcast_podcasts", "image_url")
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "podcast_podcasts",
        sa.Column("image_url", sa.VARCHAR(length=512), autoincrement=False, nullable=True),
    )
    op.add_column(
        "podcast_podcasts",
        sa.Column("rss_link", sa.VARCHAR(length=128), autoincrement=False, nullable=True),
    )
    op.add_column(
        "podcast_episodes",
        sa.Column("file_name", sa.VARCHAR(length=128), autoincrement=False, nullable=True),
    )
    op.add_column(
        "podcast_episodes", sa.Column("file_size", sa.INTEGER(), autoincrement=False, nullable=True)
    )
    op.add_column(
        "podcast_episodes",
        sa.Column("image_url", sa.VARCHAR(length=512), autoincrement=False, nullable=True),
    )
    op.add_column(
        "podcast_episodes",
        sa.Column("remote_url", sa.VARCHAR(length=128), autoincrement=False, nullable=True),
    )
    # ### end Alembic commands ###
