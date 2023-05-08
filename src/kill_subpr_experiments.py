import multiprocessing
import random
import time


def func(number):
    print("f")
    a = 0
    for i in range(1, 10):
        time.sleep(0.3)
        a += random.randint(1, 100)
        print('Processing ' + str(number) + f': prints | {a=} | ' + str(number * i))

    return a


terminate_me = False


def put_result(queue, number):
    result = func(number)
    queue.put(result)


def run_and_terminate():
    result_queue = multiprocessing.Queue()

    process = multiprocessing.Process(target=put_result, args=(result_queue, 10))
    process.start()

    # run_subprocess(result_queue)
    print("waiting...")
    time.sleep(random.randint(2, 3))
    if process.is_alive():
        process.terminate()
        print("terminated")
        return

    print("result: ", result_queue.get())


if __name__ == '__main__':
    run_and_terminate()


