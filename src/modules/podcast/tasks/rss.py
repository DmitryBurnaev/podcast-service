import os

from jinja2 import Template
from sqlalchemy import update

from common.db_utils import make_sync_session_maker
from core import settings
from common.enums import FileType
from common.storage import StorageS3
from modules.media.models import File
from modules.podcast.models import Podcast, Episode
from modules.podcast.tasks.base import RQTask, TaskState, StateData
from modules.podcast.utils import get_file_size

__all__ = ["GenerateRSSTask"]


class GenerateRSSTask(RQTask):
    """Allows recreating and upload RSS for specific podcast or for all of exists"""

    storage: StorageS3

    async def run(self, *podcast_ids: int, **_) -> TaskState:
        """Run process for generation and upload RSS to the cloud (S3)"""

        self.storage = StorageS3()
        filter_kwargs = {"id__in": map(int, podcast_ids)} if podcast_ids else {}
        podcasts = await Podcast.async_filter(self.db_session, **filter_kwargs)
        results = {}

        # TODO: remove after teardown logic testing
        print("sleep")
        import time
        time.sleep(10)

        for podcast in podcasts:
            results.update(await self._generate(podcast))

        if TaskState.ERROR in results.values():
            return TaskState.ERROR

        return TaskState.FINISHED

    async def _generate(self, podcast: Podcast) -> dict:
        """Render RSS and upload it"""

        self.logger.info("START rss generation for %s", podcast)
        local_path = await self._render_rss_to_file(podcast)
        remote_path = self.storage.upload_file(local_path, dst_path=settings.S3_BUCKET_RSS_PATH)
        if not remote_path:
            self.logger.error("Couldn't upload RSS file to storage. SKIP")
            return {podcast.id: TaskState.ERROR}

        rss_data = {
            "path": remote_path,
            "size": get_file_size(local_path, logger=self.logger),
            "available": True,
        }
        if podcast.rss_id:
            await File.async_update(self.db_session, {"id": podcast.rss_id}, rss_data)
        else:
            rss_file = await File.create(
                self.db_session,
                file_type=FileType.RSS,
                owner_id=podcast.owner_id,
                **rss_data,
            )
            await podcast.update(self.db_session, rss_id=rss_file.id)

        self.logger.info("Podcast #%i: RSS file uploaded, podcast record updated", podcast.id)
        self.logger.info("FINISH generation for %s | PATH: %s", podcast, remote_path)
        return {podcast.id: TaskState.FINISHED}

    async def _render_rss_to_file(self, podcast: Podcast) -> str:
        """Generate rss for Podcast and Episodes marked as "published" """

        self.logger.info("Podcast #%i: RSS generation has been started", podcast.id)
        episodes = await Episode.async_filter(
            self.db_session,
            podcast_id=podcast.id,
            status=Episode.Status.PUBLISHED,
            published_at__ne=None,
        )
        context = {"episodes": episodes, "settings": settings}
        rss_path = settings.TEMPLATE_PATH / "rss" / "feed_template.xml"
        with open(rss_path, encoding="utf-8") as f:
            template = Template(f.read())

        rss_filename = os.path.join(settings.TMP_RSS_PATH, f"{podcast.publish_id}.xml")
        self.logger.info("Podcast #%i: Generation new file rss [%s]", podcast.id, rss_filename)
        with open(rss_filename, "wt", encoding="utf-8") as f:
            result_rss = template.render(podcast=podcast, **context)
            f.write(result_rss)

        self.logger.info("Podcast #%i: RSS file %s generated.", podcast.id, rss_filename)
        return rss_filename

    def teardown(self, state_data: StateData) -> None:
        # todo: remove this test scenario
        episode_id = 344
        # if episode_id := state_data.data.get("episode_id"):
        session = make_sync_session_maker()
        with session.begin() as session:
            stmt = (
                update(Episode)
                .where(Episode.id == episode_id)
                .values(status=Episode.Status.ERROR)
            )
            session.execute(stmt)
