#!/bin/bash

# exp_sched.sh を様々なパラメータで繰り返し実行したいときに使う

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

sudo ./exp_sched.sh \
    --scheduler-bin scx_null \
    --scheduler-args "" \
    --bpf-fs-dir /sys/fs/bpf/scx_null \
    --workload-cmd "python3 read_trace.py --outputfile result01" \
    --outdir results/scx_null/${TIMESTAMP}/

sleep 10

sudo ./exp_sched.sh \
    --scheduler-bin scx_hybrid \
    --scheduler-args "--fifo-cpus 0-15 --cfs-cpus 16-31 --preemption-ns 1633000000 --global-cfs" \
    --bpf-fs-dir /sys/fs/bpf/scx_hybrid \
    --workload-cmd "python3 read_trace.py --outputfile result01" \
    --outdir results/scx_hybrid/${TIMESTAMP}/
