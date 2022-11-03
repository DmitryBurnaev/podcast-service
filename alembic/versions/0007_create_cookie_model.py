"""Create cookie model

Revision ID: 0007
Revises: 0006
Create Date: 2022-01-21 18:23:24.246648

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "podcast_cookies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.VARCHAR(16), nullable=True),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ("created_by_id",),
            ["auth_users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("podcast_episodes", sa.Column("cookie_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "podcast_episodes_cookie_id_fkey",
        "podcast_episodes",
        "podcast_cookies",
        ["cookie_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("podcast_episodes_cookie_id_fkey", "podcast_episodes", type_="foreignkey")
    op.drop_column("podcast_episodes", "cookie_id")
    op.drop_table("podcast_cookies")
    # ### end Alembic commands ###