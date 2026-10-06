#!/bin/zsh
exec taskset -c 0-27 chrt -o 0 /home/hirata/git/hybrid-scheduler/project/function_trace/launch_function.out 45 1
