#!/bin/bash

set -x

__D="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

__ARTIFACTS=10.42.0.1:9000

set +x
echo "=========== JOB YAML ================="
cat "$1"
echo "=========== END OF JOB YAML ==========="
set -x

# https://stackoverflow.com/a/49035906/1291457
slugify () {
    echo "$1" | iconv -t ascii//TRANSLIT | sed -r s/[~\^]+//g | sed -r s/[^a-zA-Z0-9]+/-/g | sed -r s/^-+\|-+$//g | tr A-Z a-z
}

ls -l results
[ -d results ] && rm -rf results
mkdir -pv results
touch results/"${CI_JOB_NAME}".stamp
__JOB_NAME=$(slugify "$CI_JOB_NAME")
python3 "$__D"/client.py run -w "$1" -j "$__JOB_NAME" -s results
__JOB_RESULT=$?

exit $__JOB_RESULT
