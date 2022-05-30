"""add device_cname

Revision ID: 2591cd0b1be8
Revises: cbb771a98db5
Create Date: 2022-05-25 22:17:41.087116

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2591cd0b1be8'
down_revision = 'cbb771a98db5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('devices', sa.Column('device_cname', sa.String(length=100), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('devices', 'device_cname')
    # ### end Alembic commands ###