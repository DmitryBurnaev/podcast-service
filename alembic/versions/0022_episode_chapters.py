"""Episode: chapters

Revision ID: 0022
Revises: 0021
Create Date: 2024-08-01 16:06:04.591151

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "podcast_episodes",
        sa.Column(
            "chapters", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("podcast_episodes", "chapters")
    # ### end Alembic commands ###