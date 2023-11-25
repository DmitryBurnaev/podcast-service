"""UserIP: store hashed address

Revision ID: 0019
Revises: 0018
Create Date: 2023-11-25 16:09:03.717222

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_auth_user_ips_ip_address", table_name="auth_user_ips")
    op.alter_column("auth_user_ips", column_name="ip_address", new_column_name="hashed_address")
    op.create_index(
        op.f("ix_auth_user_ips_hashed_address"), "auth_user_ips", ["hashed_address"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_auth_user_ips_hashed_address"), table_name="auth_user_ips")
    op.alter_column("auth_user_ips", column_name="hashed_address", new_column_name="auth_user_ips")
    op.create_index("ix_auth_user_ips_ip_address", "auth_user_ips", ["ip_address"], unique=False)
