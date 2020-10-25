import argparse

import worker
from redis import Redis

from core import settings
from modules.podcast import tasks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("task_name", choices=["regenerate_rss"])
    args = p.parse_args()
    print(f" ===== Run task {args.task_name} ===== ",)
    rq_queue = worker.Queue(
        name="youtube_downloads",
        connection=Redis(*settings.REDIS_CON),
        default_timeout=settings.RQ_DEFAULT_TIMEOUT,
    )
    rq_queue.enqueue(getattr(tasks, args.task_name))


if __name__ == "__main__":
    main()
