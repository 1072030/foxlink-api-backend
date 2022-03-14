"""add default admin

Revision ID: b1f242730736
Revises: 998c7cea1952
Create Date: 2022-03-14 13:42:48.820599

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1f242730736"
down_revision = "998c7cea1952"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "INSERT INTO `users` VALUES ('admin', '$2a$12$q5AbRyzYuMS8QOKPGIvq8.Wa3J8gYUUM6u/GEwlSHnxEW3W9Oa3u.', 'Foxlink Admin', '[]', NULL, 1, 1, 3)"
    )


def downgrade():
    op.execute("DELETE FROM `users` WHERE username = 'admin'")
