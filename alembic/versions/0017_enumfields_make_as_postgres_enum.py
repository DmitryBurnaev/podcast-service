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


def change_to_upper(table: str, column: str):
    bind = op.get_bind()
    query = f"""
        UPDATE {table}
        SET {column} = UPPER({column}) WHERE {column} IS NOT NULL 
    """
    bind.execute(text(query))


def convert_to_enum(table: str, column: str, enum_values: tuple[str, ...]):
    bind = op.get_bind()
    enum_type_name = f"{table}__{column}"
    enum_psql_type = postgresql.ENUM(*enum_values, name=enum_type_name)
    enum_psql_type.create(bind, checkfirst=True)
    bind.execute(
        f"""
            ALTER TABLE {table} ALTER COLUMN {column} TYPE {enum_type_name}
            USING {column}::{enum_type_name};        
        """
    )


def change_to_lower(table: str, column: str):
    bind = op.get_bind()
    bind.execute(
        f"""
            UPDATE {table}
            SET {column} = LOWER({column}) WHERE {column} IS NOT NULL;
        """
    )


def convert_back_to_varchar(table: str, column: str, column_type: str = "VARCHAR(16)"):
    bind = op.get_bind()
    enum_type_name = f"{table}__{column}"
    bind.execute(
        f"""
            ALTER TABLE {table} ALTER COLUMN {column} TYPE {column_type}
            USING {column}::{column_type};        
        """
    )
    bind.execute(f"DROP TYPE IF EXISTS {enum_type_name}")


def upgrade():
    change_to_upper(table="media_files", column="type")
    # TODO: fix error with data inserts (type correction)
    convert_to_enum(table="media_files", column="type", enum_values=MEDIA_TYPE_ENUM)

    change_to_upper(table="podcast_cookies", column="source_type")
    convert_to_enum(table="podcast_cookies", column="source_type", enum_values=SOURCE_TYPE_ENUM)

    change_to_upper(table="podcast_episodes", column="source_type")
    convert_to_enum(table="podcast_episodes", column="source_type", enum_values=SOURCE_TYPE_ENUM)

    change_to_upper(table="podcast_episodes", column="status")
    convert_to_enum(table="podcast_episodes", column="status", enum_values=STATUS_ENUM)

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
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("podcast_episodes_podcast_id_fkey", "podcast_episodes", type_="foreignkey")
    op.create_foreign_key(
        "podcast_episodes_podcast_id_fkey",
        "podcast_episodes",
        "podcast_podcasts",
        ["podcast_id"],
        ["id"],
        ondelete="CASCADE",
    )
    convert_back_to_varchar(table="podcast_episodes", column="status")
    change_to_lower(table="podcast_episodes", column="status")

    convert_back_to_varchar(table="podcast_episodes", column="source_type")
    change_to_lower(table="podcast_episodes", column="source_type")

    convert_back_to_varchar(table="podcast_cookies", column="source_type")
    change_to_lower(table="podcast_cookies", column="source_type")

    convert_back_to_varchar(table="media_files", column="type")
    change_to_lower(table="media_files", column="type")
