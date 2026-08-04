#!/bin/bash
#
# scx_* スケジューラ実験自動化スクリプト
#
# 流れ:
#   1. スケジューラを起動 (バックグラウンド)
#   2. ワークロードを起動 (フォアグラウンドで実行完了を待つ)
#   3. ワークロードが終了したら，スケジューラを停止 (SIGINT)
#   4. tasknew_map / firstrun_map / taskdead_map を bpftool でダンプ
#   5. ワークロードの標準出力 (idx=.../tid=.../n=...) と突き合わせて CSV を生成
#
# 使い方:
#   sudo ./run_experiment.sh \
#       --scheduler-bin ./scx_hybrid \
#       --scheduler-args "--fifo-cpus 0-9 --cfs-cpus 10-29" \
#       --bpf-fs-dir /sys/fs/bpf/scx_hybrid \
#       --workload-cmd "python3 read_trace.py --outputfile result01" \
#       --outdir results/run1
#
# 前提:
#   - スケジューラのローダーは SIGINT (Ctrl-C) で正常停止する実装であること
#     (scx_hybrid.c / scx_null.c は既にそう実装済み)
#   - tasknew_map / firstrun_map / taskdead_map が --bpf-fs-dir 配下に
#     pin されていること (bpf_object__pin_maps(skel->obj, BPF_FS_DIR) 済み)
#   - bpftool, python3 が PATH 上にあること
#
set -euo pipefail

# ---- デフォルト値 -------------------------------------------------------
SCHEDULER_BIN=""
SCHEDULER_ARGS=""
BPF_FS_DIR="/sys/fs/bpf/scx_hybrid"
WORKLOAD_CMD=""
OUTDIR="./scx_experiment_$(date +%Y%m%d_%H%M%S)"
SCHED_STARTUP_WAIT=2    # スケジューラが attach するまでの待機秒数
SCHED_SHUTDOWN_WAIT=30  # スケジューラが SIGINT 後に終了するまでの最大待機秒数

usage() {
    cat <<EOF
Usage: $0 --scheduler-bin <path> --workload-cmd "<cmd>" [options]

Required:
  --scheduler-bin <path>     起動するスケジューラのローダー実行ファイル (例: ./scx_hybrid)
  --workload-cmd  <cmd>      実行するワークロードのコマンドライン (クォートで囲む)

Options:
  --scheduler-args <args>    スケジューラに渡す引数 (クォートで囲む)
  --bpf-fs-dir <dir>         スケジューラが Map を pin するディレクトリ
                             (default: /sys/fs/bpf/scx_hybrid)
  --outdir <dir>             結果を書き出すディレクトリ
                             (default: ./scx_experiment_<timestamp>)
  --startup-wait <sec>       スケジューラ起動後、ワークロード起動までの待機秒数 (default: 2)
  --shutdown-wait <sec>      スケジューラ停止を待つ最大秒数 (default: 30)
  -h, --help                 このヘルプを表示
EOF
}

# ---- 引数パース ----------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --scheduler-bin)   SCHEDULER_BIN="$2";      shift 2 ;;
        --scheduler-args)  SCHEDULER_ARGS="$2";     shift 2 ;;
        --bpf-fs-dir)      BPF_FS_DIR="$2";         shift 2 ;;
        --workload-cmd)    WORKLOAD_CMD="$2";       shift 2 ;;
        --outdir)          OUTDIR="$2";             shift 2 ;;
        --startup-wait)    SCHED_STARTUP_WAIT="$2"; shift 2 ;;
        --shutdown-wait)   SCHED_SHUTDOWN_WAIT="$2";shift 2 ;;
        -h|--help)         usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ -z "$SCHEDULER_BIN" || -z "$WORKLOAD_CMD" ]]; then
    echo "Error: --scheduler-bin and --workload-cmd are required" >&2
    usage
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "Error: this script must be run as root (sudo)," \
         "since it loads a sched_ext BPF scheduler and dumps pinned BPF maps." >&2
    exit 1
fi

command -v bpftool >/dev/null 2>&1 || { echo "Error: bpftool not found in PATH" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 not found in PATH" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$OUTDIR"
SCHED_LOG="$OUTDIR/scheduler.log"
WORKLOAD_LOG="$OUTDIR/workload.log"
TASKNEW_JSON="$OUTDIR/tasknew_map.json"
FIRSTRUN_JSON="$OUTDIR/firstrun_map.json"
TASKDEAD_JSON="$OUTDIR/taskdead_map.json"
RESULT_CSV="$OUTDIR/metrics.csv"
PYTHON_TIMESTAMP_CSV="$OUTDIR/result_launch_timestamps.csv"
MERGE_CSV="$OUTDIR/merge.csv"

echo "== 結果出力先: $OUTDIR"

SCHED_PID=""

# 途中でエラーが起きた場合、スケジューラが動いたままにならないよう掃除する
cleanup_on_error() {
    if [[ -n "$SCHED_PID" ]] && kill -0 "$SCHED_PID" 2>/dev/null; then
        echo "!! エラー発生。スケジューラ (pid=$SCHED_PID) を停止します" >&2
        kill -INT "$SCHED_PID" 2>/dev/null || true
    fi
}
trap cleanup_on_error ERR

# ---- 0. bpf-fs-dir の既存 pin をクリーンアップ & CPU の設定-----------------
# 前回実行時に pin された Map がディレクトリに残っていると、
# bpf_object__pin_maps() が -EEXIST で失敗することがあるため、
# スケジューラ起動前に空にしておく (再実行の冪等性を確保する)。
echo "== [0/5] $BPF_FS_DIR の既存 pin をクリーンアップ"
mkdir -p "$BPF_FS_DIR"
find "$BPF_FS_DIR" -mindepth 1 -maxdepth 1 -exec rm -f {} +

# ハイパースレッディングをオフ
#echo off | sudo tee /sys/devices/system/cpu/smt/control
# CPU 周波数を固定
sudo cpupower -c 0-31 frequency-set -u 4.5GHz
sudo cpupower -c 0-31 frequency-set -d 4.5GHz
sudo cpupower -c 0-31 frequency-set -g performance

# ---- 1. スケジューラ起動 -------------------------------------------------
echo "== [1/5] スケジューラ起動: $SCHEDULER_BIN $SCHEDULER_ARGS"
# shellcheck disable=SC2086
sudo "$SCHEDULER_BIN" $SCHEDULER_ARGS > "$SCHED_LOG" 2>&1 &
SCHED_PID=$!

sleep "$SCHED_STARTUP_WAIT"

if ! kill -0 "$SCHED_PID" 2>/dev/null; then
    echo "Error: スケジューラの起動に失敗しました。$SCHED_LOG を確認してください" >&2
    cat "$SCHED_LOG" >&2
    exit 1
fi
echo "   -> スケジューラ起動完了 (pid=$SCHED_PID)"

# ---- 2. ワークロード起動 (完了まで待つ) -----------------------------------
cd /home/hirata/git/hybrid-scheduler
source .venv/bin/activate
cd project/function_trace
mkdir -p $OUTDIR
ulimit -n 65536
echo "== [2/5] ワークロード起動: $WORKLOAD_CMD"
eval "$WORKLOAD_CMD" > "$WORKLOAD_LOG" 2>&1
echo "   -> ワークロード完了 (ログ: $WORKLOAD_LOG)"

# ---- 3. スケジューラ停止 --------------------------------------------------
echo "== [3/5] スケジューラ停止 (SIGINT, pid=$SCHED_PID)"
kill -INT "$SCHED_PID"

waited=0
while kill -0 "$SCHED_PID" 2>/dev/null; do
    sleep 1
    waited=$((waited + 1))
    if (( waited >= SCHED_SHUTDOWN_WAIT )); then
        echo "!! スケジューラが ${SCHED_SHUTDOWN_WAIT}秒以内に終了しなかったため SIGKILL します" >&2
        kill -KILL "$SCHED_PID" 2>/dev/null || true
        break
    fi
done
wait "$SCHED_PID" 2>/dev/null || true
SCHED_PID=""
echo "   -> スケジューラ停止完了"

trap - ERR

# ---- 4. BPF Map をダンプ -------------------------------------------------
echo "== [4/5] BPF Map ダンプ (from $BPF_FS_DIR)"
for name in tasknew firstrun taskdead; do
    map_path="$BPF_FS_DIR/${name}_map"
    out_json="$OUTDIR/${name}_map.json"
    if [[ ! -e "$map_path" ]]; then
        echo "Error: $map_path が見つかりません" \
             "(スケジューラが Map を pin しましたか？ --bpf-fs-dir は正しいですか？)" >&2
        exit 1
    fi
    bpftool map dump pinned "$map_path" -j > "$out_json"
    echo "   -> $map_path を $out_json に保存"
done

# ---- 5. CSV 生成 ----------------------------------------------------------
echo "== [5/5] CSV 生成"
python3 "$SCRIPT_DIR/merge_metrics.py" \
    --tasknew "$TASKNEW_JSON" \
    --firstrun "$FIRSTRUN_JSON" \
    --taskdead "$TASKDEAD_JSON" \
    --workload-log "$WORKLOAD_LOG" \
    --out "$RESULT_CSV"

python3 "$SCRIPT_DIR/merge_bpf_timestamp_data_and_python_timestamp_data.py" \
    --o "$MERGE_CSV" \
    "$PYTHON_TIMESTAMP_CSV" \
    "$RESULT_CSV" \

echo "== 完了: $MERGE_CSV"
