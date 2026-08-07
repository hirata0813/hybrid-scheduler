#!/usr/bin/env python3
"""
BPF Map (tasknew/firstrun/taskdead) の `bpftool map dump pinned <path> -j`
出力と、ワークロードの標準出力 (idx=... tid=... n=... 形式の行) を
PID (= tid) で突き合わせて CSV (PID,tasknew,firstrun,taskdead,n,idx) を生成する。

ワークロードログから idx/tid/n の行が1つも抽出できなかった場合 (空ログ等) は、
3つの BPF Map に登場する PID (キー) の和集合を使ってマージする
(n, idx は空欄になる)。

単体でも使える:
    python3 merge_metrics.py \
        --tasknew tasknew_map.json \
        --firstrun firstrun_map.json \
        --real_firstrun real_firstrun_map.json \
        --taskdead taskdead_map.json \
        --workload-log workload.log \
        --out metrics.csv
"""
import argparse
import csv
import json
import re
import sys

# 例: "idx=194 tid=196966 n=43" のような行にマッチする。
# 行内に他の文字列が混ざっていても (前後にログprefixが付いていても) 拾えるよう
# search() で使う。
WORKLOAD_LINE_RE = re.compile(
    r"idx=(?P<idx>\d+)\s+tid=(?P<tid>\d+)\s+n=(?P<n>\d+)"
)


def load_map_json(path):
    """`bpftool map dump pinned <path> -j` の出力を {pid: value} の dict に変換する。

    bpftool は BTF 情報があるとエントリごとに以下の3通りの情報を出す:
      - "key"/"value"    : 生のバイト列 (リトルエンディアン等、アーキ依存)
      - "formatted"      : BTF を使ってデコードされた整数 (推奨、アーキ非依存)

    "formatted" があればそちらを優先し、無い場合のみ "key"/"value" の
    バイト列を自前でリトルエンディアン decode する (フォールバック)。
    """
    with open(path) as f:
        entries = json.load(f)

    result = {}
    for e in entries:
        formatted = e.get("formatted")

        if formatted is not None and "key" in formatted and "value" in formatted:
            key = formatted["key"]
            value = formatted["value"]
        else:
            key = e.get("key")
            value = e.get("value")

            if isinstance(key, list):
                key = int.from_bytes(bytes(key), byteorder="little")
            if isinstance(value, list):
                value = int.from_bytes(bytes(value), byteorder="little")

        result[int(key)] = int(value)

    return result


def parse_workload_log(path):
    """ワークロードの標準出力ログから idx/tid/n を1行ずつ抽出する。"""
    entries = []
    with open(path) as f:
        for line in f:
            m = WORKLOAD_LINE_RE.search(line)
            if not m:
                continue
            entries.append(
                {
                    "idx": int(m.group("idx")),
                    "tid": int(m.group("tid")),
                    "n": int(m.group("n")),
                }
            )
    return entries


def build_rows_from_workload(workload_entries, tasknew_map, firstrun_map, real_firstrun_map, taskdead_map):
    """通常経路: ワークロードログの各行 (idx/tid/n) を軸にマージする。"""
    rows = []
    missing_pids = []

    for entry in workload_entries:
        pid = entry["tid"]

        tasknew = tasknew_map.get(pid)
        firstrun = firstrun_map.get(pid)
        real_firstrun = real_firstrun_map.get(pid)
        taskdead = taskdead_map.get(pid)

        if tasknew is None or firstrun is None or real_firstrun is None or taskdead is None:
            missing_pids.append(pid)

        rows.append(
            [
                pid,
                "" if tasknew is None else tasknew,
                "" if firstrun is None else firstrun,
                "" if real_firstrun is None else real_firstrun,
                "" if taskdead is None else taskdead,
                entry["n"],
                entry["idx"],
            ]
        )

    return rows, missing_pids


def build_rows_from_maps(tasknew_map, firstrun_map, real_firstrun, taskdead_map):
    """フォールバック経路: workload.log が空 (idx/tid/n を1行も抽出できなかった)
    場合に使う。3つの BPF Map に登場する PID の和集合を使ってマージする。
    n, idx はワークロードログ由来の情報がないため空欄にする。
    """
    rows = []
    missing_pids = []

    all_pids = sorted(
        set(tasknew_map) | set(firstrun_map) | set(real_firstrun_map) |set(taskdead_map)
    )

    for pid in all_pids:
        tasknew = tasknew_map.get(pid)
        firstrun = firstrun_map.get(pid)
        real_firstrun = real_firstrun_map.get(pid)
        taskdead = taskdead_map.get(pid)

        if tasknew is None or firstrun is None or taskdead is None:
            missing_pids.append(pid)

        rows.append(
            [
                pid,
                "" if tasknew is None else tasknew,
                "" if firstrun is None else firstrun,
                "" if real_firstrun is None else real_firstrun,
                "" if taskdead is None else taskdead,
                "",
                "",
            ]
        )

    return rows, missing_pids


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasknew", required=True, help="tasknew_map の bpftool JSON ダンプ")
    ap.add_argument("--firstrun", required=True, help="firstrun_map の bpftool JSON ダンプ")
    ap.add_argument("--real_firstrun", required=True, help="real_firstrun_map の bpftool JSON ダンプ")
    ap.add_argument("--taskdead", required=True, help="taskdead_map の bpftool JSON ダンプ")
    ap.add_argument("--workload-log", required=True, help="ワークロードの標準出力ログ")
    ap.add_argument("--out", required=True, help="出力 CSV パス")
    args = ap.parse_args()

    tasknew_map = load_map_json(args.tasknew)
    firstrun_map = load_map_json(args.firstrun)
    real_firstrun_map = load_map_json(args.real_firstrun)
    taskdead_map = load_map_json(args.taskdead)

    workload_entries = parse_workload_log(args.workload_log)

    if workload_entries:
        rows, missing_pids = build_rows_from_workload(
            workload_entries, tasknew_map, firstrun_map, real_firstrun_map, taskdead_map
        )
        source_desc = f"workload.log ({args.workload_log}) の {len(rows)} 行"
    else:
        print(
            f"Warning: {args.workload_log} から idx/tid/n の行を"
            " 1つも抽出できませんでした。"
            " BPF Map 上の PID の和集合を使ってマージします"
            " (n, idx 列は空欄になります)",
            file=sys.stderr,
        )
        rows, missing_pids = build_rows_from_maps(
            tasknew_map, firstrun_map, real_firstrun_map, taskdead_map
        )
        source_desc = f"BPF Map 由来の PID {len(rows)} 件"

    with open(args.out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["PID", "tasknew", "firstrun", "real_firstrun", "taskdead", "n", "idx"])
        writer.writerows(rows)

    print(f"{source_desc} を {args.out} に書き出しました")
    if missing_pids:
        uniq = sorted(set(missing_pids))
        print(
            f"Warning: {len(uniq)} 個の PID が"
            " 少なくとも1つの BPF Map 上に見つかりませんでした"
            f" (例: {uniq[:10]})",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
