"""test6

Revision ID: 63bbf98fd253
Revises: 082893f84c69
Create Date: 2022-11-23 17:12:30.447321

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '63bbf98fd253'
down_revision = '082893f84c69'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('mission_events', sa.Column('created_date', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.add_column('mission_events', sa.Column('updated_date', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.add_column('users', sa.Column('created_date', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.add_column('users', sa.Column('updated_date', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'updated_date')
    op.drop_column('users', 'created_date')
    op.drop_column('mission_events', 'updated_date')
    op.drop_column('mission_events', 'created_date')
    # ### end Alembic commands ###
