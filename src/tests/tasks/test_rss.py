import os
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import FileType
from modules.auth.models import User
from modules.media.models import File
from modules.podcast import tasks
from modules.podcast.models import Episode, Podcast
from modules.podcast.tasks.base import TaskResultCode
from modules.podcast.utils import get_file_size
from tests.helpers import get_episode_data, get_podcast_data, create_episode
from tests.mocks import MockS3Client

pytestmark = pytest.mark.asyncio


class TestGenerateRSSTask:
    """Checks RSS generation logic"""

    async def test_generate__single_podcast__ok(
        self,
        dbs: AsyncSession,
        user: User,
        mocked_s3: MockS3Client,
    ):
        podcast_1: Podcast = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))
        podcast_2: Podcast = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))

        ep_data = get_episode_data(podcast_1, creator=user)
        ep_new = await create_episode(dbs, ep_data, status=Episode.Status.NEW)

        ep_data = get_episode_data(podcast_1, creator=user)
        ep_downloading = await create_episode(dbs, ep_data, status=Episode.Status.DOWNLOADING)

        ep_data = get_episode_data(podcast_1, creator=user)
        ep_data["published_at"] = datetime.now()
        ep_published = await create_episode(dbs, ep_data, status=Episode.Status.PUBLISHED)
        await ep_published.update(dbs, chapters=[{"title": "Chapter1", "start": "00:00:01"}])

        ep_data = get_episode_data(podcast_2, creator=user)
        ep_podcast_2 = await create_episode(dbs, ep_data, status=Episode.Status.PUBLISHED)

        await dbs.commit()

        expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast_1.publish_id}.xml"
        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await generate_rss_task.run(podcast_1.id)
        assert result_code == TaskResultCode.SUCCESS

        assert os.path.exists(expected_file_path), f"File {expected_file_path} didn't uploaded"
        with open(expected_file_path) as f:
            generated_rss_content = f.read()

        assert ep_published.title in generated_rss_content
        assert ep_published.description in generated_rss_content
        assert ep_published.watch_url in generated_rss_content
        audio: File = await File.async_get(dbs, id=ep_published.audio_id)
        assert audio.url in generated_rss_content
        assert "Chapter1" in generated_rss_content

        for episode in [ep_new, ep_downloading, ep_podcast_2]:
            audio: File = await File.async_get(dbs, id=episode.audio_id)
            audio_url = audio.url or "in-progress"
            assert audio_url not in generated_rss_content, f"wrong {episode} in RSS {podcast_1}"

        podcast_1 = await Podcast.async_get(dbs, id=podcast_1.id)
        assert podcast_1.rss_id is not None
        rss: File = await File.async_get(dbs, id=podcast_1.rss_id)
        assert rss.available is True
        assert rss.type == FileType.RSS
        assert rss.path == str(expected_file_path)
        assert rss.size == get_file_size(expected_file_path)

    async def test_regenerate__replace_rss(
        self,
        dbs: AsyncSession,
        podcast: Podcast,
        mocked_s3: MockS3Client,
    ):
        old_rss_id = podcast.rss_id
        expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast.publish_id}.xml"
        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await generate_rss_task.run(podcast.id)
        assert result_code == TaskResultCode.SUCCESS

        await dbs.refresh(podcast)
        assert podcast.rss_id == old_rss_id

        rss: File = await File.async_get(dbs, id=podcast.rss_id)
        assert rss.available is True
        assert rss.type == FileType.RSS
        assert rss.path == str(expected_file_path)
        assert rss.size == get_file_size(expected_file_path)
        mocked_s3.delete_files_async.assert_not_awaited()

    async def test_generate__several_podcasts__ok(
        self,
        dbs: AsyncSession,
        user: User,
        mocked_s3: MockS3Client,
    ):
        podcast_1 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))
        podcast_2 = await Podcast.async_create(dbs, **get_podcast_data(owner_id=user.id))
        await dbs.commit()

        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await generate_rss_task.run(podcast_1.id, podcast_2.id)
        assert result_code == TaskResultCode.SUCCESS

        for podcast in [podcast_1, podcast_2]:
            expected_file_path = mocked_s3.tmp_upload_dir / f"{podcast.publish_id}.xml"
            assert os.path.exists(expected_file_path), f"File {expected_file_path} didn't uploaded"

    async def test_generate__upload_failed__fail(
        self,
        dbs: AsyncSession,
        podcast: Podcast,
        mocked_s3: MockS3Client,
    ):
        old_path = "/remote/old_path.rss"
        mocked_s3.upload_file.side_effect = lambda *_, **__: ""
        await File.async_update(
            dbs, filter_kwargs={"id": podcast.rss_id}, update_data={"path": old_path}
        )

        generate_rss_task = tasks.GenerateRSSTask(db_session=dbs)
        result_code = await generate_rss_task.run(podcast.id)
        assert result_code == TaskResultCode.ERROR

        podcast_1 = await Podcast.async_get(dbs, id=podcast.id)
        assert podcast_1.rss_id is not None
        rss: File = await File.async_get(dbs, id=podcast.rss_id)
        assert rss.path == old_path
