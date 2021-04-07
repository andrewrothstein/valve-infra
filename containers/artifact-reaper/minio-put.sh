#!/bin/bash

# Based on https://github.com/kneufeld/minio-put

set -o errexit
set -o pipefail
set -o xtrace


if [ ! -d /results ]; then
    echo "ERROR: /results is not mounted, nothing to archive!"
    exit 1
fi

if [ -z "$CI_JOB_ID" ]; then
    echo "ERROR: no CI_JOB_ID set in the environment, can not disambiguate storage paths!"
    exit 1
fi

file=${CI_JOB_ID}-artifacts.tgz
tar cvzf $file -C /results .

host=${S3_HOST:-10.42.0.1:9000}
#s3_key=${S3_KEY:-secret key}
#s3_secret=${S3_SECRET:-secret token}

resource="/jobs/$file"
content_type="application/octet-stream"
date=`date -R`

curl -v -X PUT -T "${file}" \
          -H "Host: $host" \
          -H "Date: ${date}" \
          -H "Content-Type: ${content_type}" \
          http://$host${resource}
