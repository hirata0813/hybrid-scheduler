import re
import time
import argparse
import asyncio
import os
import ctypes
import struct
 
# ---------------------------------------------------------------------------
# BPF Map ("othertask_map") に自身の tid を登録するためのヘルパー
#
# 目的:
#   このプロセス (read_trace.py) 自身は launch_function.out (fib計算) を
#   起動するだけの「その他」タスクであり、BPF スケジューラ側で
#   launch_function 由来のタスクと区別して扱いたい。
#   そのため、起動時に自分の tid を pin 済みの othertask_map に書き込み、
#   BPF プログラム側 (select_cpu/enqueue 等) がこの Map を lookup することで
#   「これは launch_function ではない」と判定できるようにする。
#
# 前提:
#   - othertask_map は BPF 側 (hybrid_scx.bpf.c) で
#         struct {
#             __uint(type, BPF_MAP_TYPE_HASH);
#             __uint(max_entries, 8192);
#             __type(key, pid_t);
#             __type(value, u8);
#         } othertask_map SEC(".maps");
#     のような形で定義され、ローダー側 (hybrid_scx.c) で
#     OTHERTASK_MAP_PIN_PATH に pin されていること。
#     (まだ実装していない場合は、tasknew_map 等と同様に追加が必要)
#   - bpf() syscall番号は x86_64 (321) を前提にしている。
#     他アーキで動かす場合は BPF_SYSCALL_NR を要調整。
# ---------------------------------------------------------------------------
 
# read_trace.py などワークロード以外のプロセスは，この Map に登録して，実行 CPU を固定する
OTHERTASK_MAP_PIN_PATH = "/sys/fs/bpf/scx_hybrid/debug_filter"
 
BPF_SYSCALL_NR = 321  # x86_64
BPF_MAP_UPDATE_ELEM = 2
BPF_OBJ_GET = 7
BPF_ANY = 0
 
_libc = ctypes.CDLL("libc.so.6", use_errno=True)
 
class _BpfAttrObjGet(ctypes.Structure):
    _fields_ = [
        ("pathname", ctypes.c_uint64),
        ("bpf_fd", ctypes.c_uint32),
        ("file_flags", ctypes.c_uint32),
    ]
 
 
class _BpfAttrMapElem(ctypes.Structure):
    _fields_ = [
        ("map_fd", ctypes.c_uint32),
        ("_pad0", ctypes.c_uint32),
        ("key", ctypes.c_uint64),
        ("value", ctypes.c_uint64),
        ("flags", ctypes.c_uint64),
    ]
 
 
def _bpf(cmd, attr, size):
    ret = _libc.syscall(BPF_SYSCALL_NR, cmd, ctypes.byref(attr), size)
    if ret < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"bpf(cmd={cmd}) failed: {os.strerror(errno)}")
    return ret
 
 
def bpf_obj_get(pin_path: str) -> int:
    """pin されている BPF オブジェクト(Map等)の fd を BPF_OBJ_GET で取得する。"""
    path_buf = ctypes.create_string_buffer(pin_path.encode())
    attr = _BpfAttrObjGet()
    attr.pathname = ctypes.cast(path_buf, ctypes.c_void_p).value
    attr.bpf_fd = 0
    attr.file_flags = 0
    return _bpf(BPF_OBJ_GET, attr, ctypes.sizeof(attr))
 
 
def bpf_map_update_elem(map_fd: int, key: bytes, value: bytes, flags: int = BPF_ANY) -> int:
    """BPF_MAP_UPDATE_ELEM で key/value を書き込む。"""
    key_buf = ctypes.create_string_buffer(key)
    val_buf = ctypes.create_string_buffer(value)
    attr = _BpfAttrMapElem()
    attr.map_fd = map_fd
    attr.key = ctypes.cast(key_buf, ctypes.c_void_p).value
    attr.value = ctypes.cast(val_buf, ctypes.c_void_p).value
    attr.flags = flags
    return _bpf(BPF_MAP_UPDATE_ELEM, attr, ctypes.sizeof(attr))
 
 
def register_self_as_other_task():
    """自身の tid を othertask_map に登録する。
 
    失敗しても (例: Map が未 pin, 権限不足等) ワークロード実行自体は
    継続できるよう、例外は握りつぶして warning を出すだけにしている。
    """
    try:
        map_fd = bpf_obj_get(OTHERTASK_MAP_PIN_PATH)
    except OSError as e:
        print(
            f"[warn] othertask_map ({OTHERTASK_MAP_PIN_PATH}) のオープンに"
            f" 失敗しました (BPF プログラムが未ロード、または pin パスが"
            f" 異なる可能性があります): {e}"
        )
        return
 
    tid = os.getpid()  # このプロセス自身の tid
    key = struct.pack("<I", tid)  # pid_t (u32, little endian)
    value = struct.pack("<B", 1)  # u8: 1 = "other" タスクであることを示す
 
    try:
        bpf_map_update_elem(map_fd, key, value)
        print(f"[info] othertask_map に自身の tid={tid} を登録しました")
    except OSError as e:
        print(f"[warn] othertask_map への書き込みに失敗しました: {e}")
    finally:
        os.close(map_fd)

def _set_sched_ext():
    """子プロセスのexec直前に呼ばれ、SCHED_EXTポリシーを要求する。
    SCHED_EXT の値(7)はカーネル側の /usr/include/linux/sched.h に定義されている
    整数値で、util-linux(chrt)のバージョンには依存しない。
    """
    os.sched_setscheduler(0, 7, os.sched_param(0))

# Launch the C++ fibonacci function
async def launch_command_cpp(arg, idx):
    command = (
        f"sudo chrt -o 0 /home/hirata/git/hybrid-scheduler/project/function_trace/launch_function.out {arg} {idx}"
    )
    print(command)

    # ext クラスへの変更のため，テストとして以下を入れている
    #process = await asyncio.create_subprocess_shell(
    #    command,
    #    preexec_fn=_set_sched_ext,   # fork直後・exec直前にサブプロセス側で実行される
    #)
    process = await asyncio.create_subprocess_shell(command)
    await process.communicate()


async def launch_command_firecraker(firecracker_id, time):
    command = f"/home/shared/serverlessinterface/cold {firecracker_id} {time}"
    print(command)
    process = await asyncio.create_subprocess_shell(command)
    await process.communicate()


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

    # log the results to the output file
    with open(f"../log/{outputfile}.txt", "a") as f:
        f.write(f"time elapsed: {end - start} s\n")


# Launch the C++ fibonacci function according to the trace file IAT
async def main_firecracker(outputfile):
    tasks = []
    # Read trace file
    with open(
        "/home/hirata/git/hybrid-scheduler/project/serverless_workload_generator/workload_dur.txt", "r"
    ) as f:
        start = time.time()
        lines = f.readlines()
        for i, line in enumerate(lines):
            IAT = float(line.split(" ")[0])
            arg = int(line.split(" ")[1])  # arg is fibonacci N
            await asyncio.sleep(IAT)  # sleep for IAT seconds
            delay = map(arg)
            task = asyncio.create_task(launch_command_firecraker(i, delay))
            tasks.append(task)

    # Wait for all tasks to complete
    await asyncio.gather(*tasks)

    end = time.time()
    print("Time elapsed: {:.2f} s".format(end - start))
    # log the results to the output file
    with open(f"../log/{outputfile}.txt", "a") as f:
        f.write(f"time elapsed: {end - start} s\n")


def map(arg):
    if arg <= 44:
        return 1
    elif arg == 45:
        return 2
    elif arg == 46:
        return 3

def exclude_self_from_sched_ext():
    """
    switch_all 有効時でも sched_ext は SCHED_NORMAL/BATCH/IDLE のタスクしか
    扱わないため、自分自身を SCHED_FIFO (リアルタイム) に変えることで
    sched_ext の管理対象から外れる。

    SCHED_RESET_ON_FORK を同時に指定しておくことで、このプロセスから
    fork/exec される子プロセス (launch_function.out) は通常の
    SCHED_NORMAL に戻り、sched_ext の制御下に残る
    (= ワークロード側は今まで通り分離対象になる)。
    """
    reset_on_fork = getattr(os, "SCHED_RESET_ON_FORK", 0x40000000)
    policy = os.SCHED_FIFO | reset_on_fork
    param = os.sched_param(1)  # 最低優先度。ほぼsleepしかしないので他を飢餓させない
    os.sched_setscheduler(0, policy, param)


if __name__ == "__main__":
    print("read_trace.py PID:", os.getpid())
    # 自身の tid を othertask_map に登録し、BPF スケジューラ側から
    # launch_function とは別種のタスクとして識別できるようにする
    register_self_as_other_task()
    #exclude_self_from_sched_ext()
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputfile", type=str)
    args = parser.parse_args()
    outputfile = args.outputfile
    asyncio.run(main(outputfile))
    # asyncio.run(main_firecracker(outputfile))
