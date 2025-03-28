"""Add new column

Revision ID: 657a42252e73
Revises: 
Create Date: 2025-03-28 09:52:47.635231

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '657a42252e73'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name_en', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('name_zh', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('mobile', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('password', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ticket',
    sa.Column('device_model', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('customer', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('fault_phenomenon', sa.Text(), nullable=False),
    sa.Column('fault_reason', sa.Text(), nullable=False),
    sa.Column('handling_method', sa.Text(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('create_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('userhistory',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('changed_id', sa.Integer(), nullable=False),
    sa.Column('before_info', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('after_info', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('change_reason', sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False),
    sa.Column('changed_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['changed_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('attachment',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('file_path', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('file_type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('upload_time', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['ticket_id'], ['ticket.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('tickethistory',
    sa.Column('device_model', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('customer', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('fault_phenomenon', sa.Text(), nullable=False),
    sa.Column('fault_reason', sa.Text(), nullable=False),
    sa.Column('handling_method', sa.Text(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('changer_id', sa.Integer(), nullable=False),
    sa.Column('create_at', sa.DateTime(), nullable=False),
    sa.Column('change_notes', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['changer_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['ticket_id'], ['ticket.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ticketattachmentlink',
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('attachment_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['attachment_id'], ['attachment.id'], ),
    sa.ForeignKeyConstraint(['ticket_id'], ['ticket.id'], ),
    sa.PrimaryKeyConstraint('ticket_id', 'attachment_id')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('ticketattachmentlink')
    op.drop_table('tickethistory')
    op.drop_table('attachment')
    op.drop_table('userhistory')
    op.drop_table('ticket')
    op.drop_table('user')
    # ### end Alembic commands ###
