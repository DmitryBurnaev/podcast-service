"""User IPs: added field registred_by

Revision ID: 0012
Revises: 0011
Create Date: 2022-05-22 16:16:43.905285

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "auth_user_ips",
        sa.Column("registered_by", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_index(
        op.f("ix_auth_user_ips_registered_by"), "auth_user_ips", ["registered_by"], unique=False
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_auth_user_ips_registered_by"), table_name="auth_user_ips")
    op.drop_column("auth_user_ips", "registered_by")
    # ### end Alembic commands ###