"""Files: added hash field

Revision ID: 0016
Revises: 0015
Create Date: 2022-08-21 19:43:30.571685

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "media_files", sa.Column("hash", sa.String(length=32), nullable=False, server_default="")
    )


def downgrade():
    op.drop_column("media_files", "hash")
