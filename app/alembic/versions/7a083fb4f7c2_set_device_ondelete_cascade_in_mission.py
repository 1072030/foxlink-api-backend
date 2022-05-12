"""set device ondelete=CASCADE in mission

Revision ID: 7a083fb4f7c2
Revises: cc44d3a86d3b
Create Date: 2022-05-12 20:17:18.949346

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a083fb4f7c2'
down_revision = 'cc44d3a86d3b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_missions_devices_id_device', 'missions', type_='foreignkey')
    op.create_foreign_key('fk_missions_devices_id_device', 'missions', 'devices', ['device'], ['id'], ondelete='CASCADE')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_missions_devices_id_device', 'missions', type_='foreignkey')
    op.create_foreign_key('fk_missions_devices_id_device', 'missions', 'devices', ['device'], ['id'])
    # ### end Alembic commands ###
