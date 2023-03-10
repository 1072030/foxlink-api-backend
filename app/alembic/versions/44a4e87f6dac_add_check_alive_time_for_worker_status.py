"""add check_alive_time for worker status

Revision ID: 44a4e87f6dac
Revises: 0bc92997b835
Create Date: 2022-03-29 02:35:35.322403

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '44a4e87f6dac'
down_revision = '0bc92997b835'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('worker_status', sa.Column('check_alive_time', sa.DateTime(), server_default=sa.text('now()'), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('worker_status', 'check_alive_time')
    # ### end Alembic commands ###
