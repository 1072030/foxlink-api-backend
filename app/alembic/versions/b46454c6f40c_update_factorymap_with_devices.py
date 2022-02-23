"""update factorymap with devices

Revision ID: b46454c6f40c
Revises: 9520129333da
Create Date: 2022-02-23 20:16:47.741354

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b46454c6f40c"
down_revision = "9520129333da"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "factorymaps", sa.Column("related_devices", sa.JSON(), nullable=False)
    )


def downgrade():
    op.drop_column("factorymaps", "related_devices")
