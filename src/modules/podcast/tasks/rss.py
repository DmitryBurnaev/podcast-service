import os

from jinja2 import Template

from core import settings
from common.storage import StorageS3
from common.utils import get_logger
from modules.podcast.models import Podcast, Episode
from modules.podcast.tasks.base import RQTask, FinishCode

logger = get_logger(__name__)
__all__ = ["GenerateRSSTask"]


class GenerateRSSTask(RQTask):
    """ Allows to recreate and upload RSS for specific podcast or for all of exists """

    storage: StorageS3 = None

    async def run(self, *podcast_ids: int) -> FinishCode:
        """ Run process for generation and upload RSS to the cloud (S3) """

        self.storage = StorageS3()
        filter_kwargs = {"id__in": map(int, podcast_ids)} if podcast_ids else {}
        podcasts = await Podcast.async_filter(**filter_kwargs)
        results = {}
        for podcast in podcasts:
            results.update(await self._generate(podcast))

        logger.info("Regeneration results: \n%s", results)

        if FinishCode.ERROR in results.values():
            return FinishCode.ERROR

        return FinishCode.OK

    async def _generate(self, podcast: Podcast) -> dict:
        """ Render RSS and upload it """

        logger.info("START rss generation for %s", podcast)
        result_path = await self._render_rss_to_file(podcast)

        result_url = self.storage.upload_file(result_path, dst_path=settings.S3_BUCKET_RSS_PATH)
        if not result_url:
            logger.error("Couldn't upload RSS file to storage. SKIP")
            return {podcast.id: FinishCode.ERROR}

        await podcast.update(rss_link=str(result_url)).apply()
        logger.info("RSS file uploaded, podcast record updated")

        logger.info("FINISH generation for %s | URL: %s", podcast, podcast.rss_link)
        return {podcast.id: FinishCode.OK}

    @staticmethod
    async def _render_rss_to_file(podcast: Podcast) -> str:
        """ Generate rss for Podcast and Episodes marked as "published" """

        logger.info(f"Podcast #{podcast.id}: RSS generation has been started.")

        episodes = await Episode.async_filter(
            podcast_id=podcast.id,
            status=Episode.Status.PUBLISHED,
            published_at__ne=None,
        )
        context = {"episodes": episodes, "settings": settings}
        with open(os.path.join(settings.TEMPLATE_PATH, "rss", "feed_template.xml")) as fh:
            template = Template(fh.read())

        rss_filename = os.path.join(settings.TMP_RSS_PATH, f"{podcast.publish_id}.xml")
        logger.info(f"Podcast #{podcast.publish_id}: Generation new file rss [{rss_filename}]")
        with open(rss_filename, "w") as fh:
            result_rss = template.render(podcast=podcast, **context)
            fh.write(result_rss)

        logger.info(f"Podcast #{podcast.id}: RSS generation has been finished.")
        return rss_filename
