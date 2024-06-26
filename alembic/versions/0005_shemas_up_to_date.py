"""shemas_up_to_date

Revision ID: 0005
Revises: 0004
Create Date: 2021-07-15 23:35:29.506142

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "auth_users",
        "email",
        existing_type=sa.VARCHAR(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "auth_users",
        "email",
        existing_type=sa.String(length=128),
        type_=sa.VARCHAR(length=32),
        existing_nullable=False,
    )
    # ### end Alembic commands ###
