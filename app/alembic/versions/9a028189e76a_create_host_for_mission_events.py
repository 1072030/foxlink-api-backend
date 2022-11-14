"""create host for mission events

Revision ID: 9a028189e76a
Revises: df73de6f903f
Create Date: 2022-11-14 15:58:00.612238

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a028189e76a'
down_revision = 'df73de6f903f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('missionevents', sa.Column('host', sa.String(30)))


def downgrade():
    op.drop_column('missionevents',sa.Column('host'))
