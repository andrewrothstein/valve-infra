#!/bin/bash

set -x

__D="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

__ARTIFACTS=10.42.0.1:9000

set +x
echo "=========== JOB YAML ================="
cat "$1"
echo "=========== END OF JOB YAML ==========="
set -x

ls -l results
[ -d results ] && rm -rf results
mkdir -pv results
touch results/"${CI_JOB_NAME}".stamp
python3 "$__D"/client.py run -w "$1" -j "$CI_JOB_NAME" -s results
__JOB_RESULT=$?

exit $__JOB_RESULT
