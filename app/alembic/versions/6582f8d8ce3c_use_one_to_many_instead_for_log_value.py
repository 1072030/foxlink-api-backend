"""use one to many instead for log value

Revision ID: 6582f8d8ce3c
Revises: cd96b3de09f5
Create Date: 2022-04-23 05:06:36.055931

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '6582f8d8ce3c'
down_revision = 'cd96b3de09f5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('auditlogheaders_logvalues')
    op.add_column('logvalues', sa.Column('log_header', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_logvalues_auditlogheaders_id_log_header', 'logvalues', 'auditlogheaders', ['log_header'], ['id'], ondelete='CASCADE')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_logvalues_auditlogheaders_id_log_header', 'logvalues', type_='foreignkey')
    op.drop_column('logvalues', 'log_header')
    op.create_table('auditlogheaders_logvalues',
    sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('logvalue', mysql.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('auditlogheader', mysql.INTEGER(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['auditlogheader'], ['auditlogheaders.id'], name='fk_auditlogheaders_logvalues_auditlogheaders_auditlogheader_id', onupdate='CASCADE', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['logvalue'], ['logvalues.id'], name='fk_auditlogheaders_logvalues_logvalues_logvalue_id', onupdate='CASCADE', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mysql_collate='utf8mb4_0900_ai_ci',
    mysql_default_charset='utf8mb4',
    mysql_engine='InnoDB'
    )
    # ### end Alembic commands ###
