import os
import logging

from jinja2 import Template

from core import settings
from common.enums import FileType
from common.storage import StorageS3
from modules.media.models import File
from modules.podcast.utils import get_file_size
from modules.podcast.models import Podcast, Episode
from modules.podcast.tasks.base import RQTask, TaskResultCode

__all__ = ["GenerateRSSTask"]
logger = logging.getLogger(__name__)


class GenerateRSSTask(RQTask):
    """Allows recreating and upload RSS for specific podcast or for all of exists"""

    storage: StorageS3

    async def run(self, *podcast_ids: int, **_) -> TaskResultCode:
        """Run process for generation and upload RSS to the cloud (S3)"""

        self.storage = StorageS3()
        filter_kwargs = {"id__in": map(int, podcast_ids)} if podcast_ids else {}
        podcasts = await Podcast.async_filter(self.db_session, **filter_kwargs)
        results = {}

        for podcast in podcasts:
            results.update(await self._generate(podcast))

        if TaskResultCode.ERROR in results.values():
            return TaskResultCode.ERROR

        return TaskResultCode.SUCCESS

    async def _generate(self, podcast: Podcast) -> dict:
        """Render RSS and upload it"""

        logger.info("START rss generation for %s", podcast)
        local_path = await self._render_rss_to_file(podcast)
        remote_path = self.storage.upload_file(local_path, dst_path=settings.S3_BUCKET_RSS_PATH)
        if not remote_path:
            logger.error("Couldn't upload RSS file to storage. SKIP")
            return {podcast.id: TaskResultCode.ERROR}

        rss_data = {
            "path": remote_path,
            "size": get_file_size(local_path),
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

        logger.info("Podcast #%i: RSS file uploaded, podcast record updated", podcast.id)
        logger.info("FINISH generation for %s | PATH: %s", podcast, remote_path)
        return {podcast.id: TaskResultCode.SUCCESS}

    async def _render_rss_to_file(self, podcast: Podcast) -> str:
        """Generate rss for Podcast and Episodes marked as "published" """

        logger.info("Podcast #%i: RSS generation has been started", podcast.id)
        episodes = await Episode.async_filter(
            self.db_session,
            podcast_id=podcast.id,
            status=Episode.Status.PUBLISHED,
            published_at__ne=None,
        )
        context = {"episodes": episodes, "settings": settings}
        logger.info("Podcast #%i: Adding chapters", podcast.id)
        rss_path = settings.TEMPLATE_PATH / "rss" / "feed_template.xml"

        with open(rss_path, encoding="utf-8") as f:
            template = Template(f.read(), trim_blocks=True)

        rss_filename = os.path.join(settings.TMP_RSS_PATH, f"{podcast.publish_id}.xml")
        logger.info("Podcast #%i: Generation new file rss [%s]", podcast.id, rss_filename)
        with open(rss_filename, "wt", encoding="utf-8") as f:
            result_rss = template.render(podcast=podcast, **context)
            f.write(result_rss)

        logger.info("Podcast #%i: RSS file %s generated.", podcast.id, rss_filename)
        return rss_filename
