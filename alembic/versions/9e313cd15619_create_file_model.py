"""Create file model

Revision ID: 9e313cd15619
Revises: da63661dc19a
Create Date: 2022-04-15 09:20:31.654464

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9e313cd15619'
down_revision = 'da63661dc19a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        'media_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('type', sa.VARCHAR(16), nullable=False),
        sa.Column('path', sa.String(length=256), nullable=False),
        sa.Column('size', sa.Integer(), nullable=True),
        sa.Column('source_url', sa.String(length=512), nullable=False, default=''),
        sa.Column('available', sa.Boolean(), nullable=False, default=False),
        sa.Column('access_token', sa.String(length=128), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(('owner_id',), ['auth_users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Episode indexes | Episode.audio | Episode.image_id
    op.create_index(op.f('ix_media_files_access_token'), 'media_files', ['access_token'], unique=True)
    op.create_index(op.f('ix_media_files_owner_id'), 'media_files', ['owner_id'], unique=False)
    op.add_column('podcast_episodes', sa.Column('audio_id', sa.Integer(), nullable=True))
    op.add_column('podcast_episodes', sa.Column('image_id', sa.Integer(), nullable=True))
    op.drop_index('ix_podcast_episodes_created_by_id', table_name='podcast_episodes')
    op.create_index(op.f('ix_podcast_episodes_owner_id'), 'podcast_episodes', ['owner_id'], unique=False)
    op.create_foreign_key('podcast_episodes_image_id_fkey', 'podcast_episodes', 'media_files', ['image_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('podcast_episodes_audio_id_fkey', 'podcast_episodes', 'media_files', ['audio_id'], ['id'], ondelete='SET NULL')

    # Podcast.image_id
    op.add_column('podcast_podcasts', sa.Column('image_id', sa.Integer(), nullable=True))
    op.create_foreign_key('podcast_podcasts_image_id_fkey', 'podcast_podcasts', 'media_files', ['image_id'], ['id'], ondelete='SET NULL')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    # Podcast.image_id
    op.drop_constraint('podcast_podcasts_image_id_fkey', 'podcast_podcasts', type_='foreignkey')
    op.drop_column('podcast_podcasts', 'image_id')

    # Episode indexes | Episode.audio | Episode.image_id
    op.drop_constraint('podcast_episodes_image_id_fkey', 'podcast_episodes', type_='foreignkey')
    op.drop_constraint('podcast_episodes_audio_id_fkey', 'podcast_episodes', type_='foreignkey')
    op.drop_index(op.f('ix_podcast_episodes_owner_id'), table_name='podcast_episodes')
    op.create_index('ix_podcast_episodes_created_by_id', 'podcast_episodes', ['owner_id'], unique=False)
    op.drop_column('podcast_episodes', 'image_id')
    op.drop_column('podcast_episodes', 'audio_id')

    # File
    op.drop_index(op.f('ix_media_files_owner_id'), table_name='media_files')
    op.drop_index(op.f('ix_media_files_access_token'), table_name='media_files')
    op.drop_table('media_files')

    # ### end Alembic commands ###
