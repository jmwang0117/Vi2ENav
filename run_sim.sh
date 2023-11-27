#!/bin/bash

SESSION_NAME="ego_planner"

# Create a new tmux session
tmux new-session -d -s "$SESSION_NAME"

# Execute the commands in each window
tmux send-keys -t "$SESSION_NAME:0" 'source ~/Vi2ENav/devel/setup.bash; roslaunch ego_planner simple_run.launch' C-m
#tmux new-window -t "$SESSION_NAME" 'sleep 2; source ~/Vi2ENav/devel/setup.bash; roslaunch ego_planner run_in_sim.launch'
tmux new-window -t "$SESSION_NAME" 'sleep 2;rostopic echo /planning/pos_cmd'

# Attach to the tmux session
tmux attach-session -t "$SESSION_NAME"
