import multiprocessing
import time


def func(number):
    print("f")
    for i in range(1, 10):
        time.sleep(1)
        print('Processing ' + str(number) + ': prints ' + str(number * i))

#
#         def worker(return_dict):
#             """worker function"""
#             print(str(procnum) + " represent!")
#             return_dict[procnum] = procnum
#
#         run_task_function = partial(asyncio.run, self._perform_and_run(*args, **kwargs))
#         sub_process = multiprocessing.Process(target=run_task_function)
#         sub_process.start()
#         sub_process.


if __name__ == '__main__':
    # list of all processes, so that they can be killed afterwards
    print("start")
    all_processes = []

    for i in range(0, 3):
        print(f"start {i}")
        process = multiprocessing.Process(target=func, args=(i,))
        process.start()
        all_processes.append(process)

    # kill all processes after 0.03s
    time.sleep(2)
    for process in all_processes:
        print(f"terminating {process}")
        process.terminate()


