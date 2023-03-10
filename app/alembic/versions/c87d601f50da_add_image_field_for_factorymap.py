"""add image field for factorymap

Revision ID: c87d601f50da
Revises: 6582f8d8ce3c
Create Date: 2022-05-11 02:57:38.886286

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c87d601f50da'
down_revision = '6582f8d8ce3c'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('factorymaps', sa.Column('image', sa.LargeBinary(length=5242880), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('factorymaps', 'image')
    # ### end Alembic commands ###
