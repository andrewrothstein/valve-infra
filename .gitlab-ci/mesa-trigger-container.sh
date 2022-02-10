#!/bin/sh

set -eu

python3 -m pip install --upgrade pip
pip install ./executor/client ./valvetraces
wget --progres=dot:mega -O /usr/bin/mcli https://dl.min.io/client/mc/release/linux-amd64/mc && chmod +x /usr/bin/mcli
