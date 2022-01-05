#!/bin/bash

set -eux

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
D="$SCRIPT_DIR"/../

__vivian_tmux_session="Vivian"
if !  tmux list-sessions | grep -q $__vivian_tmux_session ; then
    tmux new-session -d -s $__vivian_tmux_session

    tmux rename-window -t 0 'Status'
    #tmux send-keys -t 'Status' "make -C $D/containers/valve-infra/ REGISTRY=10.0.2.2:8088 CONTAINER=mupuf/valve-infra/valve-infra-$USER:latest vivian" C-m
    tmux send-keys -t 'Status' "make -C $D/containers/valve-infra/ IPXE_ISO=$D/ipxe-boot-server/infra_isos/ci-gateway-tchar-vivian.iso vivian-ipxe" C-m

    tmux new-window -t $__vivian_tmux_session:1 -n 'Gateway Shell'
    tmux send-keys -t 'Gateway Shell' C-m 'clear' C-m "make -C $D/containers/valve-infra/ REGISTRY=10.0.2.2:8088 CONTAINER=mupuf/valve-infra/valve-infra-$USER:latest vivian-connect" C-m

    tmux new-window -t $__vivian_tmux_session:2 -n 'vPDU server'
    tmux send-keys -t 'vPDU server' "python3 $SCRIPT_DIR/../vivian/vpdu.py --port 9191" C-m

    tmux new-window -t $__vivian_tmux_session:3 -n 'vPDU status'
    tmux send-keys -t 'vPDU status' "watch -n10 python3 $SCRIPT_DIR/../vivian/client.py --status" C-m

    tmux new-window -t $__vivian_tmux_session:4 -n 'Gateway PDUs'
    tmux send-keys -t 'Gateway PDUs' "watch -n10 \"curl -sL localhost:8001/api/v1/pdu | jq\"" C-m

    tmux new-window -t $__vivian_tmux_session:5 -n 'Gateway Machines'
    tmux send-keys -t 'Gateway Machines' "watch -n10 \"curl -sL localhost:8000/api/v1/machines | jq\"" C-m
fi

tmux attach-session -t $__vivian_tmux_session:0
