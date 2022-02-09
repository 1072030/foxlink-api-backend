"""add init admin

Revision ID: 962cd169c651
Revises: 474345f1c8fd
Create Date: 2022-02-09 17:16:10.884489

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "962cd169c651"
down_revision = "474345f1c8fd"
branch_labels = None
depends_on = None

# Default Username: admin, Password: foxlink
def upgrade():
    op.execute(
        "INSERT INTO `users` VALUES (1, 'admin', '$2a$12$q5AbRyzYuMS8QOKPGIvq8.Wa3J8gYUUM6u/GEwlSHnxEW3W9Oa3u.', 'Foxlink Admin', '[]', NULL, 1, 1, 3)"
    )


def downgrade():
    op.execute("DELETE FROM `users` WHERE `id` = 1")
