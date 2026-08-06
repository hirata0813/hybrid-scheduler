#!/bin/bash

# exp_sched.sh を様々なパラメータで繰り返し実行したいときに使う

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

#sudo ./exp_sched.sh \
#    --scheduler-bin scx_null \
#    --scheduler-args "" \
#    --bpf-fs-dir /sys/fs/bpf/scx_null \
#    --workload-cmd "python3 read_trace.py --outputfile result01" \
#    --outdir results/scx_null/${TIMESTAMP}/
#
#sleep 10

sudo ./exp_sched.sh \
    --scheduler-bin scx_hybrid \
    --scheduler-args "--fifo-cpus 0,1,2,3,4,5,6,7,16,17,18,19,20,21 --cfs-cpus 8,9,10,11,12,13,14,15,22,23,24,25,26,27 --preemption-ns 1633000000 --global-cfs" \
    --bpf-fs-dir /sys/fs/bpf/scx_hybrid \
    --workload-cmd "taskset -c 31 chrt -f 50 python3 /home/hirata/git/hybrid-scheduler/project/function_trace/read_trace.py --outputfile results/scx_hybrid/${TIMESTAMP}/" \
    --outdir results/scx_hybrid/${TIMESTAMP}/
