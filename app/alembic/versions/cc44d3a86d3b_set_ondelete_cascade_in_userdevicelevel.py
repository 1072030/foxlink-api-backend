"""set ondelete=CASCADE in userdevicelevel

Revision ID: cc44d3a86d3b
Revises: c87d601f50da
Create Date: 2022-05-12 19:55:49.012971

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cc44d3a86d3b'
down_revision = 'c87d601f50da'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_userdevicelevels_devices_id_device', 'userdevicelevels', type_='foreignkey')
    op.create_foreign_key('fk_userdevicelevels_devices_id_device', 'userdevicelevels', 'devices', ['device'], ['id'], ondelete='CASCADE')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_userdevicelevels_devices_id_device', 'userdevicelevels', type_='foreignkey')
    op.create_foreign_key('fk_userdevicelevels_devices_id_device', 'userdevicelevels', 'devices', ['device'], ['id'])
    # ### end Alembic commands ###
