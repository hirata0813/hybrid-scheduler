#!/usr/bin/env python3
"""
scx_* スケジューラ実験の metrics.csv (PID,tasknew,firstrun,taskdead,n,idx) を
読み込み、各タスクの

  - response time  (rt)  = firstrun - tasknew
  - execution time (et)  = taskdead - firstrun
  - turnaround time (tat) = taskdead - tasknew

を計算し、その統計 (平均・90%ile・99%ile・最小・最大) を表示する。

rt/et/tat のいずれか1つでも値が負になったタスクは、そのタスクの内容と
件数だけを表示し、当該タスクを rt/et/tat すべての統計 (summary) から
除外する (どれか1つでも負なら、そのタスクは丸ごと除外)。

使い方:
    python3 analyze_metrics.py metrics.csv
    python3 analyze_metrics.py metrics.csv --unit us
    python3 analyze_metrics.py metrics.csv \
        --per-task-out per_task.csv --summary-out summary.csv
"""
import argparse
import csv
import math
import statistics
import sys


def percentile(sorted_values, p):
    """線形補間による百分位数 (numpy.percentile のデフォルト方式と同じ)。

    sorted_values は昇順ソート済みであること。
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]

    k = (len(sorted_values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[int(f)] * (c - k)
    d1 = sorted_values[int(c)] * (k - f)
    return d0 + d1


def load_tasks(path):
    """CSV を読み込み、各タスクの rt/et/tat (ns) を計算して返す。"""
    tasks = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        required = {"PID", "tasknew", "firstrun", "taskdead"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"Error: {path} に必要な列がありません: {sorted(missing)}")

        for lineno, row in enumerate(reader, start=2):
            pid = row["PID"]
            try:
                tasknew = int(row["tasknew"])
                firstrun = int(row["firstrun"])
                taskdead = int(row["taskdead"])
            except (ValueError, TypeError):
                print(
                    f"Warning: {path}:{lineno} (PID={pid}) の"
                    " tasknew/firstrun/taskdead が数値でないためスキップします",
                    file=sys.stderr,
                )
                continue

            if not (tasknew <= firstrun <= taskdead):
                print(
                    f"Warning: {path}:{lineno} (PID={pid}) は時刻の順序が"
                    f" tasknew({tasknew}) <= firstrun({firstrun}) <= taskdead({taskdead})"
                    " になっていません。計算はしますが値が負になる可能性があります",
                    file=sys.stderr,
                )

            tasks.append(
                {
                    "PID": pid,
                    "tasknew": tasknew,
                    "firstrun": firstrun,
                    "taskdead": taskdead,
                    "n": row.get("n", ""),
                    "idx": row.get("idx", ""),
                    "response_time_ns": firstrun - tasknew,
                    "execution_time_ns": taskdead - firstrun,
                    "turnaround_time_ns": taskdead - tasknew,
                }
            )
    return tasks


def summarize(values):
    """1つのメトリクス(値のリスト)に対して分布の全体像がわかる統計量を計算する。

    平均・最小・最大に加え、25/50(中央値)/75/90/99 %ile を出すことで、
    テール(90/99%ile)だけでなく分布全体の形もわかるようにする。
    """
    if not values:
        return {
            "n": 0, "mean": None, "min": None,
            "p25": None, "p50": None, "p55": None,
            "p60": None, "p65": None, "p70": None,
            "p75": None, "p80": None, "p85": None,
            "p90": None, "p95": None, "p99": None, "max": None,
        }
    sorted_values = sorted(values)
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "min": sorted_values[0],
        "p25": percentile(sorted_values, 25),
        "p50": percentile(sorted_values, 50),
        "p55": percentile(sorted_values, 55),
        "p60": percentile(sorted_values, 60),
        "p65": percentile(sorted_values, 65),
        "p70": percentile(sorted_values, 70),
        "p75": percentile(sorted_values, 75),
        "p80": percentile(sorted_values, 80),
        "p85": percentile(sorted_values, 85),
        "p90": percentile(sorted_values, 90),
        "p95": percentile(sorted_values, 95),
        "p99": percentile(sorted_values, 99),
        "max": sorted_values[-1],
    }


def split_tasks_by_any_negative(tasks, metric_keys):
    """tasks を、metric_keys のうちどれか1つでも負の値を持つかどうかで分ける。

    戻り値: (valid_tasks, negative_tasks)
      valid_tasks    -> rt/et/tat すべてが 0 以上のタスクのリスト
      negative_tasks -> rt/et/tat のいずれか1つでも負のタスクのリスト
    """
    valid = []
    negative = []
    for t in tasks:
        if any(t[key] < 0 for key in metric_keys.values()):
            negative.append(t)
        else:
            valid.append(t)
    return valid, negative


def negative_metric_names(t, metric_keys):
    """タスク t の中で値が負になっている指標名のリストを返す。"""
    return [name for name, key in metric_keys.items() if t[key] < 0]


def print_negative_tasks(negative_tasks, metric_keys, divisor, unit):
    """負の値を含むタスクの内容と件数だけを表示する(統計には含めない)。"""
    if not negative_tasks:
        return
    print(f"\n[除外] rt/et/tat のいずれかが負のタスク: {len(negative_tasks)} 件"
          "（全指標の統計から除外します）")
    print(f"  {'PID':<10}{'n':<8}{'idx':<8}"
          f"{'tasknew':>14} {'firstrun':>14} {'taskdead':>14} "
          f"{'rt(' + unit + ')':>14} {'et(' + unit + ')':>14} {'tat(' + unit + ')':>14}"
          f"  除外理由")
    for t in negative_tasks:
        rt = t["response_time_ns"] / divisor
        et = t["execution_time_ns"] / divisor
        tat = t["turnaround_time_ns"] / divisor
        reasons = ",".join(negative_metric_names(t, metric_keys))
        print(
            f"  {str(t['PID']):<10}{str(t['n']):<8}{str(t['idx']):<8}"
            f"{t['tasknew']:>14} {t['firstrun']:>14} {t['taskdead']:>14} "
            f"{rt:>14.6f} {et:>14.6f} {tat:>14.6f}"
            f"  {reasons}"
        )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("input_csv", help="metrics.csv (PID,tasknew,firstrun,taskdead,n,idx)")
    ap.add_argument(
        "--per-task-out",
        help="タスクごとの rt/et/tat を追加した CSV の書き出し先 (省略可)",
    )
    ap.add_argument(
        "--summary-out", help="集計結果 (mean/p90/p99/min/max) を書き出す CSV パス (省略可)"
    )
    ap.add_argument(
        "--unit",
        choices=["ns", "us", "ms", "s"],
        default="s",
        help="標準出力に表示する際の単位 (デフォルト: s)。CSV出力は常に ns。",
    )
    args = ap.parse_args()

    tasks = load_tasks(args.input_csv)
    if not tasks:
        sys.exit(f"Error: {args.input_csv} から有効なタスクを1件も読み込めませんでした")

    divisor = {"ns": 1, "us": 1e3, "ms": 1e6, "s": 1e9}[args.unit]

    metric_keys = {
        "response_time": "response_time_ns",
        "execution_time": "execution_time_ns",
        "turnaround_time": "turnaround_time_ns",
    }

    # rt/et/tat のいずれか1つでも負のタスクは、そのタスクを丸ごと
    # (rt/et/tat すべての統計から) 除外する。
    valid_tasks, negative_tasks = split_tasks_by_any_negative(tasks, metric_keys)
    metrics = {
        name: [t[key] for t in valid_tasks] for name, key in metric_keys.items()
    }

    print(f"タスク数(読み込み総数): {len(tasks)}")
    print(f"表示単位: {args.unit}")

    # ---- 負の値を持つデータを表示 (統計には含めない) ----
    print_negative_tasks(negative_tasks, metric_keys, divisor, args.unit)

    summary = {name: summarize(values) for name, values in metrics.items()}

    # ---- 標準出力に統計を表示 ----
    print()
    stat_keys = ("n", "mean", "min", "p25", "p50", "p55", "p60", "p65", "p70", "p75", "p80", "p85", "p90", "p95", "p99", "max")
    header = f"{'metric':<16}" + "".join(f"{k:>12}" for k in stat_keys)
    print(header)
    print("-" * len(header))
    for name, s in summary.items():
        row = f"{name:<16}"
        for key in stat_keys:
            val = s[key]
            if val is None:
                row += f"{'N/A':>12}"
            elif key == "n":
                row += f"{val:>12d}"
            else:
                row += f"{val / divisor:>12.6f}"
        print(row)
    if negative_tasks:
        print(f"\n(全指標で {len(negative_tasks)} 件のタスクを除外済み。"
              " 詳細は上記の[除外]一覧を参照)")
    print(
        "\n(p50 は中央値。p25/p50/p75 で分布の中心的な傾向、"
        " p90/p99 でテール(裾)の重さを見る。"
        " n は統計に使用した有効件数)"
    )

    # ---- per-task CSV (元データはそのまま全件出力。除外フラグ列を付与) ----
    if args.per_task_out:
        with open(args.per_task_out, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "PID", "tasknew", "firstrun", "taskdead", "n", "idx",
                    "response_time_ns", "execution_time_ns", "turnaround_time_ns",
                    "excluded", "excluded_reason",
                ]
            )
            for t in tasks:
                is_negative = any(t[key] < 0 for key in metric_keys.values())
                reasons = ";".join(negative_metric_names(t, metric_keys))
                writer.writerow(
                    [
                        t["PID"], t["tasknew"], t["firstrun"], t["taskdead"],
                        t["n"], t["idx"],
                        t["response_time_ns"], t["execution_time_ns"], t["turnaround_time_ns"],
                        "yes" if is_negative else "",
                        reasons,
                    ]
                )
        print(f"\nタスクごとの詳細を {args.per_task_out} に書き出しました"
              "（excluded 列が yes のタスクは全指標の統計から除外済み。"
              " excluded_reason 列に負だった指標名を記載）")

    # ---- summary CSV (負の値を除外した統計のみ) ----
    if args.summary_out:
        with open(args.summary_out, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["metric", "count_used", "count_excluded_negative_task",
                 "mean_ns", "min_ns", "p25_ns", "p50_ns", "p55_ns",
                 "p60_ns", "p65_ns", "p70_ns", "p75_ns", "p80_ns", "p85_ns",
                 "p90_ns", "p95_ns", "p99_ns", "max_ns"]
            )
            for name, s in summary.items():
                writer.writerow(
                    [name, s["n"], len(negative_tasks),
                     s["mean"], s["min"], s["p25"], s["p50"], s["p55"],
                     s["p60"], s["p65"], s["p70"], s["p75"], s["p80"], s["p85"],
                     s["p90"], s["p95"], s["p99"], s["max"]]
                )
        print(f"集計結果を {args.summary_out} に書き出しました"
              "（rt/et/tatのいずれかが負のタスクは全指標から除外済み。"
              " count_excluded_negative_task 列に除外件数を記載）")


if __name__ == "__main__":
    main()
