import multiprocessing
import os
import random
import subprocess
import time


def func(number):
    print("f")
    a = 0
    for i in range(1, 10):
        time.sleep(0.3)
        a += random.randint(1, 100)
        print('Processing ' + str(number) + f': prints | {a=} | ' + str(number * i))

    return a


def run_bash_script():
    subprocess.run(
        ["sleep", "125"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
        timeout=120,
    )


terminate_me = False


def put_result(queue, number):
    result = func(number)
    queue.put(result)


def run_and_terminate():
    result_queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=run_bash_script)
    # process = multiprocessing.Process(target=put_result, args=(result_queue, 10))
    process.start()

    # run_subprocess(result_queue)
    print("waiting...")
    time.sleep(random.randint(2, 3))
    if process.is_alive():
        os.system('ps aux | grep "sleep 125" | grep -v grep | awk \'{print $2}\' | xargs kill')
        # subprocess.run('ps aux | grep "sleep 125" | grep -v grep | awk "{print $2}"'.split())
        process.terminate()
        print("terminated")
        return

    print("result: ", result_queue.get())


if __name__ == '__main__':
    # run_bash_script()
    run_and_terminate()


