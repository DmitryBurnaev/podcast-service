"""Files: added hash field

Revision ID: 6d3f44425801
Revises: 6f97ecebbf04
Create Date: 2022-08-21 19:43:30.571685

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6d3f44425801'
down_revision = '6f97ecebbf04'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'media_files',
        sa.Column('hash', sa.String(length=32), nullable=False, server_default="")
    )


def downgrade():
    op.drop_column('media_files', 'hash')
