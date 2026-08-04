#!/usr/bin/env python3

import pandas as pd
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("file1", help="clock_monotonic_raw.csv")
parser.add_argument("file2", help="trace.csv")
parser.add_argument("-o", "--output", default="merged.csv")
args = parser.parse_args()

# CSVを読み込み
df1 = pd.read_csv(args.file1)
df2 = pd.read_csv(args.file2)

# idxでマージ
merged = pd.merge(df2, df1, on="idx", how="inner")

# 必要なら列順を整理
cols = [
    "PID",
    "idx",
    "n_x",           # merge後に名前が衝突するので一旦確認
    "n_y",
    "tasknew",
    "firstrun",
    "taskdead",
    "clock_monotonic_raw",
]

# n列が一致するなら1つにまとめる
if "n_x" in merged.columns:
    if (merged["n_x"] == merged["n_y"]).all():
        merged = merged.drop(columns=["n_y"]).rename(columns={"n_x": "n"})
    else:
        print("Warning: n columns do not match.")

merged.to_csv(args.output, index=False)

print(f"Saved to {args.output}")
