#!/bin/bash

set -x

__D="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

__ARTIFACTS=10.42.0.1:9000

echo "=========== JOB YAML ================="
cat "$1"
echo "=========== END OF JOB YAML ==========="

python3 "$__D"/client.py -w run "$1"
__JOB_RESULT=$?

mkdir -pv results
wget -O - http://${__ARTIFACTS}/jobs/${CI_JOB_ID}-artifacts.tgz | tar zxf - -C results

exit $__JOB_RESULT
