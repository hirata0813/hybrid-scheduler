#!/usr/bin/env bash
#
# read_trace.sh
#
# read_trace.py の shell script 版。
#
# Python版との違い:
#   - othertask_map への自身の tid 登録には、ctypes 経由の生 syscall の代わりに
#     `bpftool map update pinned ...` を使う。
#     ・これにより x86_64 決め打ちだった BPF_SYSCALL_NR (321) の考慮が不要になる。
#   - launch_function.out の起動は `cmd &` で直接 fork+exec するため、
#     asyncio.create_subprocess_shell() が内部で挟んでいた `/bin/sh -c "..."`
#     のワンクッションが無くなる(fork/execの段数が1段減る)。
#     ※ ただし fork 直後・exec 直前の「隙間」自体はOSの原理上ゼロにはならない。
#
# 使い方:
#   ./read_trace.sh --outputfile result01
#
set -uo pipefail

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
OTHERTASK_MAP_PIN_PATH="/sys/fs/bpf/scx_hybrid/debug_filter"
LAUNCH_BIN="/home/hirata/git/hybrid-scheduler/project/function_trace/launch_function.out"
TRACE_FILE="/home/hirata/git/hybrid-scheduler/project/serverless_workload_generator/workload_dur.txt"
LOG_DIR="../log"

# ---------------------------------------------------------------------------
# 引数パース (--outputfile <name>)
# ---------------------------------------------------------------------------
OUTPUTFILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --outputfile)
            OUTPUTFILE="$2"
            shift 2
            ;;
        --outputfile=*)
            OUTPUTFILE="${1#*=}"
            shift
            ;;
        *)
            echo "unknown option: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$OUTPUTFILE" ]]; then
    echo "usage: $0 --outputfile <name>" >&2
    exit 1
fi

echo "read_trace.sh PID: $$"

# ---------------------------------------------------------------------------
# 自身の tid (= このシェルプロセス自身の PID) を othertask_map に登録する。
#
# 失敗しても(Mapが未pin, bpftool不在, 権限不足等)ワークロード実行自体は
# 継続できるよう、エラーは warning に留める。
# ---------------------------------------------------------------------------
register_pid_to_map() {
    local pid="$1"

    # pid_t (u32, little endian)
    local b0=$(( pid & 0xff ))
    local b1=$(( (pid >> 8) & 0xff ))
    local b2=$(( (pid >> 16) & 0xff ))
    local b3=$(( (pid >> 24) & 0xff ))

    local key_hex
    key_hex=$(printf '%02x %02x %02x %02x' "$b0" "$b1" "$b2" "$b3")

    bpftool map update pinned "$OTHERTASK_MAP_PIN_PATH" \
        key hex $key_hex \
        value hex 01 >/dev/null 2>&1
}

register_self_as_other_task() {
    register_pid_to_map "$$"
    echo "[info] registered self ($$)"
}

register_parent_scripts() {
    local pid=$$

    while [[ "$pid" -ne 1 ]]; do
        local ppid
        ppid=$(ps -o ppid= -p "$pid" | tr -d ' ')

        local cmd
        cmd=$(ps -o args= -p "$ppid")

        case "$cmd" in
            *exp_sched.sh*|*exp_multi_sched.sh*)
                register_pid_to_map "$ppid"
                echo "[info] registered parent script: pid=$ppid ($cmd)"
                ;;
        esac

        pid=$ppid
    done
}

register_self_as_other_task
register_parent_scripts

# ---------------------------------------------------------------------------
# フィボナッチ計算 (C++バイナリ) を起動する
# ---------------------------------------------------------------------------
launch_command_cpp() {
    local arg="$1"
    local idx="$2"
    #echo "taskset -c 0,2,4,6,8,10,12,14 ${LAUNCH_BIN} ${arg} ${idx}"
    # ここで直接バイナリを fork+exec する (sh -c を挟まない)
    "$LAUNCH_BIN" "$arg" "$idx"
}

# ---------------------------------------------------------------------------
# トレースファイルを読み、IATに従ってタスクを起動する
# ---------------------------------------------------------------------------
if [[ ! -f "$TRACE_FILE" ]]; then
    echo "[error] トレースファイルが見つかりません: $TRACE_FILE" >&2
    exit 1
fi

pids=()
idx=0

start_ts=$(date +%s.%N)

# 最終行に改行が無くても読み飛ばさないように || [[ -n "$iat" ]] を付けている
while IFS=' ' read -r iat arg _rest || [[ -n "${iat:-}" ]]; do
    [[ -z "${iat:-}" ]] && continue
    sleep "$iat"
    launch_command_cpp "$arg" "$idx" &
    pids+=("$!")
    idx=$((idx + 1))
done < "$TRACE_FILE"

end_ts=$(date +%s.%N)
# 元のPython版と同様、ここで測っているのは「全タスクの起動が終わるまでの時間」
# であり、各タスクの完了(gather相当のwait)を待った時間ではない点に注意。
elapsed_launch=$(awk -v s="$start_ts" -v e="$end_ts" 'BEGIN { printf "%.2f", e - s }')
printf "タスク起動に%s sかかった\n" "$elapsed_launch"

# ---------------------------------------------------------------------------
# 全タスクの完了を待つ (asyncio.gather 相当)
# ---------------------------------------------------------------------------
for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null
done

# ---------------------------------------------------------------------------
# 結果をログファイルに書き込む
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"
echo "time elapsed: ${elapsed_launch} s" >> "${LOG_DIR}/${OUTPUTFILE}.txt"
