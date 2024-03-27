"""EnumFields: make as postgres enum

Revision ID: 0017
Revises: 0016
Create Date: 2023-01-24 09:21:16.226588

"""

from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

SOURCE_TYPE_ENUM = ("YOUTUBE", "YANDEX", "UPLOAD")
MEDIA_TYPE_ENUM = ("AUDIO", "IMAGE", "RSS")
STATUS_ENUM = ("NEW", "DOWNLOADING", "PUBLISHED", "ARCHIVED", "ERROR")


def convert_to_enum(table: str, column: str, enum_values: tuple[str, ...], enum_name: str):
    bind = op.get_bind()
    enum_psql_type = postgresql.ENUM(*enum_values, name=enum_name)
    enum_psql_type.create(bind, checkfirst=True)
    bind.execute(
        text(
            f"""
            UPDATE {table}
            SET {column} = UPPER({column}) WHERE {column} IS NOT NULL 
        """
        )
    )
    bind.execute(
        text(
            f"""
            ALTER TABLE {table} ALTER COLUMN {column} TYPE {enum_name}
            USING {column}::{enum_name};        
        """
        )
    )


def convert_to_varchar(
    table: str, column: str, column_type: str = "VARCHAR(16)", to_lower: bool = False
):
    bind = op.get_bind()
    bind.execute(
        text(
            f"""
            ALTER TABLE {table} ALTER COLUMN {column} TYPE {column_type}
            USING {column}::{column_type};        
        """
        )
    )
    if to_lower:
        bind.execute(
            text(
                f"""
                UPDATE {table}
                SET {column} = LOWER({column}) WHERE {column} IS NOT NULL;
            """
            )
        )


def upgrade():
    convert_to_enum(
        table="media_files",
        column="type",
        enum_values=MEDIA_TYPE_ENUM,
        enum_name="media_type",
    )
    convert_to_enum(
        table="podcast_cookies",
        column="source_type",
        enum_values=SOURCE_TYPE_ENUM,
        enum_name="source_type",
    )
    convert_to_enum(
        table="podcast_episodes",
        column="source_type",
        enum_values=SOURCE_TYPE_ENUM,
        enum_name="source_type",
    )
    convert_to_enum(
        table="podcast_episodes",
        column="status",
        enum_values=STATUS_ENUM,
        enum_name="episode_status",
    )

    op.drop_constraint("podcast_episodes_podcast_id_fkey", "podcast_episodes", type_="foreignkey")
    op.create_foreign_key(
        "podcast_episodes_podcast_id_fkey",
        "podcast_episodes",
        "podcast_podcasts",
        ["podcast_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint("podcast_episodes_podcast_id_fkey", "podcast_episodes", type_="foreignkey")
    op.create_foreign_key(
        "podcast_episodes_podcast_id_fkey",
        "podcast_episodes",
        "podcast_podcasts",
        ["podcast_id"],
        ["id"],
        ondelete="CASCADE",
    )

    convert_to_varchar(table="podcast_episodes", column="status", to_lower=True)
    convert_to_varchar(table="podcast_episodes", column="source_type")
    convert_to_varchar(table="podcast_cookies", column="source_type")
    convert_to_varchar(table="media_files", column="type")

    bind = op.get_bind()
    bind.execute(text("DROP TYPE IF EXISTS episode_status"))
    bind.execute(text("DROP TYPE IF EXISTS source_type"))
    bind.execute(text("DROP TYPE IF EXISTS media_type"))
