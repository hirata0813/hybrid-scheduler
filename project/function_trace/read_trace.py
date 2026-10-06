import re
import time
import argparse
import asyncio
import os
import ctypes
import struct
 
launch_timestamps = []
# Launch the C++ fibonacci function
async def launch_command_cpp(arg, idx):
    command = (
        f"taskset -c 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27 chrt -o 0 /home/hirata/git/scx/scheds/c/nonpriority-task {arg} {idx}"
    )
    #print(command)

    # create_subprocess_shell 直前の CLOCK_MONOTONIC タイムスタンプを取得し、配列に詰め込む
    monotonic_ts_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    launch_timestamps.append((idx, arg, monotonic_ts_ns))
    process = await asyncio.create_subprocess_shell(command)
    await process.communicate()

def dump_launch_timestamps(outputfile):
    """launch_timestamps の中身を idx 順に整列してログファイルへダンプする。"""
    sorted_timestamps = sorted(launch_timestamps, key=lambda t: t[0])
    dump_path = f"{outputfile}/result_launch_timestamps.csv"
    with open(dump_path, "w") as f:
        f.write("idx,n,clock_monotonic_raw\n")
        for idx, arg, ts in sorted_timestamps:
            f.write(f"{idx},{arg},{ts}\n")
    print(f"[info] launch_timestamps ({len(sorted_timestamps)} 件) を {dump_path} にダンプしました")

# Launch the C++ fibonacci function according to the trace file IAT
async def main(outputfile):
    tasks = []
    # Read trace file
    with open(
        "/home/hirata/git/hybrid-scheduler/project/serverless_workload_generator/workload_dur.txt", "r"
    ) as f:
        start = time.time()
        lines = f.readlines()
        idx = 0
        for line in lines:
            IAT = float(line.split(" ")[0])
            arg = int(line.split(" ")[1])  # arg is fibonacci N
            await asyncio.sleep(IAT)  # sleep for IAT seconds
            task = asyncio.create_task(launch_command_cpp(arg, idx))
            tasks.append(task)
            idx += 1

    # Wait for all tasks to complete
    end = time.time()
    print("タスク起動に{:.2f} sかかった".format(end - start))
    await asyncio.gather(*tasks)

    # 全タスク起動完了後、launch_timestamps の中身をダンプする
    dump_launch_timestamps(outputfile)

def map(arg):
    if arg <= 44:
        return 1
    elif arg == 45:
        return 2
    elif arg == 46:
        return 3

if __name__ == "__main__":
    print("read_trace.py PID:", os.getpid())
    # 自身の tid を othertask_map に登録し、BPF スケジューラ側から
    # launch_function とは別種のタスクとして識別できるようにする
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputfile", type=str)
    args = parser.parse_args()
    outputfile = args.outputfile
    asyncio.run(main(outputfile))
