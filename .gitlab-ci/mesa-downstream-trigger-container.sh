#!/bin/sh

set -eu

pwd ; find . -exec ls -l '{}' \;

python3 -m pip install --upgrade pip
pip install ./executor/client ./valvetraces
wget --progres=dot:mega -O /usr/bin/mcli https://dl.min.io/client/mc/release/linux-amd64/mc && chmod +x /usr/bin/mcli

cp -v containers/gitlab-trigger/bin/ensure_container.sh /usr/local/bin
cp -v containers/gitlab-trigger/bin/submit_job.sh /usr/local/bin
pip install ./executor/client ./valvetraces

# Backwards compat.
ln -sv /usr/local/bin/valvetraces /usr/local/bin/valvetraces.py
ln -sv /usr/local/bin/executorctl /usr/local/bin/client.py
