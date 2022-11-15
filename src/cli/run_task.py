import argparse

import rq
from redis import Redis

from core import settings
from modules.podcast.tasks import RQTask


def main():
    arg_parser = argparse.ArgumentParser()
    task_map = {task_class.__name__: task_class for task_class in RQTask.get_subclasses()}

    arg_parser.add_argument("task_name", choices=task_map.keys())
    arg_parser.add_argument("--args", dest="task_args", required=False, nargs="+")
    args = arg_parser.parse_args()
    rq_queue = rq.Queue(
        name=settings.RQ_QUEUE_NAME,
        connection=Redis(*settings.REDIS_CON),
        default_timeout=settings.RQ_DEFAULT_TIMEOUT,
    )
    task = task_map[args.task_name]()
    print(f" ===== Running task {task} | args: {args.task_args} ===== ")
    rq_queue.enqueue(task, *(args.task_args or []))


if __name__ == "__main__":
    main()
