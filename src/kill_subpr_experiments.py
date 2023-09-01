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
        print("Processing " + str(number) + f": prints | {a=} | " + str(number * i))

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
    time.sleep(random.randint(1, 2))
    if process.is_alive():
        grep = "sleep 125"
        print(f"ps aux | grep \"{grep}\" | grep -v grep | awk '{{print $2}}' | xargs kill ")
        os.system(f"ps aux | grep \"{grep}\" | grep -v grep | awk '{{print $2}}' | xargs kill")
        process.terminate()
        print("terminated")
        return

    print("result: ", result_queue.get())


def kill_with_sigint():
    time.sleep(10)
    print("killing")
    os.system(f"ps aux | grep \"ffmpeg\" | grep -v grep | awk '{{print $2}}' | xargs kill -SIGINT")
    print("done killing")


def run_with_sigkill():
    completed_proc = None
    try:
        ffmpeg_params = [
            "ffmpeg", "-y", "-i", "../.misc/audio/prolog.mp3", "-vn",
            "-acodec", "libmp3lame", "-q:a", "5", "../.misc/audio/tmp_prolog.mp3"
        ]
        print(" ".join(ffmpeg_params))
        completed_proc = subprocess.run(
            ffmpeg_params,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as err:
        # TODO: return code 255. check it and task state too
        err_details = f"FFMPEG cancelled??: {err.returncode} \n {err.stdout}"
        raise RuntimeError(err_details) from err

    except Exception as exc:
        err_details = f"FFMPEG failed with exit status: {completed_proc.returncode if completed_proc else 'null'}, err: {exc!r}"
        raise RuntimeError(err_details) from exc

    else:
        # process.terminate()
        print(
            "FFMPEG success done preparation for file %s:\n%s",
            completed_proc.returncode,
            str(completed_proc.stdout, encoding="utf-8"),
        )


def run_too_long_process(sleep_time: int):
    print("Start sleeping process")
    time.sleep(sleep_time)
    print("Finish sleeping process")


if __name__ == "__main__":
    # run_bash_script()
    run_with_sigkill()
    # run_too_long_process(120)
