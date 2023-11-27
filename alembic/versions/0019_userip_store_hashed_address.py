"""UserIP: store hashed address

Revision ID: 0019
Revises: 0018
Create Date: 2023-11-25 16:09:03.717222

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection

from common.utils import hash_string

# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    op.drop_index("ix_auth_user_ips_ip_address", table_name="auth_user_ips")
    op.alter_column(
        "auth_user_ips",
        column_name="ip_address",
        new_column_name="hashed_address",
        type_=sa.String(length=128),
        existing_type=sa.String(length=16),
    )
    _hash_exists_addresses(connection)
    op.create_index(
        "ix_auth_user_ips__user_id__hashed_address",
        "auth_user_ips",
        ["user_id", "hashed_address"],
        unique=False,
    )


def downgrade():
    connection = op.get_bind()
    op.drop_index(op.f("ix_auth_user_ips__user_id__hashed_address"), table_name="auth_user_ips")
    _cut_exists_addresses(connection)
    op.alter_column(
        "auth_user_ips",
        column_name="hashed_address",
        new_column_name="ip_address",
        type_=sa.String(length=16),
        existing_type=sa.String(length=128),
    )
    op.create_index("ix_auth_user_ips_ip_address", "auth_user_ips", ["ip_address"], unique=False)


def _hash_exists_addresses(connection: Connection):
    address_query = text("SELECT id, hashed_address FROM auth_user_ips")
    update_query = text("UPDATE auth_user_ips SET hashed_address = :hashed_address WHERE id = :id")

    for ip_id, ip_address in connection.execute(address_query).fetchall():
        connection.execute(update_query, {"id": ip_id, "hashed_address": hash_string(ip_address)})


def _cut_exists_addresses(connection: Connection):
    update_query = text(
        "UPDATE auth_user_ips SET hashed_address = substring(hashed_address, 1, 16)"
    )
    connection.execute(update_query)
