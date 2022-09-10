"""Rename owner field

Revision ID: 0008
Revises: 0007
Create Date: 2022-03-11 09:43:08.860202

"""
from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def rename_created_by_field(table_name: str):
    op.drop_constraint(f"{table_name}_created_by_id_fkey", table_name, type_="foreignkey")
    op.alter_column(f"{table_name}", "created_by_id", new_column_name="owner_id")
    op.create_foreign_key(
        f"{table_name}_owner_id_fkey", table_name, "auth_users", ["owner_id"], ["id"]
    )


def undo_rename_created_by_field(table_name: str):
    op.drop_constraint(f"{table_name}_owner_id_fkey", table_name, type_="foreignkey")
    op.alter_column(f"{table_name}", "owner_id", new_column_name="created_by_id")
    op.create_foreign_key(
        f"{table_name}_created_by_id_fkey", table_name, "auth_users", ["created_by_id"], ["id"]
    )


def upgrade():
    rename_created_by_field("auth_invites")
    rename_created_by_field("podcast_cookies")
    rename_created_by_field("podcast_episodes")
    rename_created_by_field("podcast_podcasts")


def downgrade():
    undo_rename_created_by_field("auth_invites")
    undo_rename_created_by_field("podcast_cookies")
    undo_rename_created_by_field("podcast_episodes")
    undo_rename_created_by_field("podcast_podcasts")
