#!/bin/bash

#set -o errexit
set -o pipefail
set -o nounset
set -o xtrace

D="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MESA_IMAGE_NAME=${MESA_IMAGE#registry.freedesktop.org/}

PULL_THRU_REGISTRY=10.42.0.1:8002
REGISTRY=10.42.0.1:8004

TEST_CONTAINER="${REGISTRY}/${MESA_IMAGE_NAME}"
KERNEL_PATH=${ARTIFACTS_URL}/${KERNEL_IMAGE_NAME}

cat <<EOF > job.yml
version: 1

# Rules to match for a machine to qualify
target:
  tags: [$CI_RUNNER_TAGS]

timeouts:
  first_console_activity:  # This limits the time it can take to receive the first console log
    minutes: 5
    retries: 0
  console_activity:  # Reset every time we receive a message from the logs
    minutes: 1
    retries: 0
  overall:           # Maximum time the job can take, not overrideable by the "continue" deployment
    hours: 2
    retries: 0
    # no retries possible here

console_patterns:
    session_end:
        regex: '^\+ poweroff -f\r$'
    job_success:
        regex: '^\+ DEQP_EXITCODE=0\r$'
    job_warn:
      regex: '^ERROR - dEQP error.*$'

# Environment to deploy
deployment:
  # Initial boot
  start:
    kernel:
      url: "http://10.42.0.1:9000/boot/default_kernel"
      cmdline:
        - b2c.container="-ti --tls-verify=false docker://${PULL_THRU_REGISTRY}/mupuf/valve-infra/machine_registration:latest check"
        - b2c.ntp_peer="10.42.0.1" b2c.pipefail b2c.cache_device=auto
        - b2c.container="-v ${CI_JOB_ID}-results:${CI_PROJECT_DIR}/results --tls-verify=false docker://$TEST_CONTAINER"
        - b2c.post_container="-v ${CI_JOB_ID}-results:/results -e CI_JOB_ID=${CI_JOB_ID} --tls-verify=false docker://${PULL_THRU_REGISTRY}/mupuf/valve-infra/artifact-reaper:latest"
        - console={{ local_tty_device }},115200 earlyprintk=vga,keep SALAD.machine_id={{ machine_id }}
        - loglevel=6

    initramfs:
      # url: "http://10.42.0.1:9000/boot/default_boot2container.cpio.xz"
      url: "https://gitlab.freedesktop.org/mupuf/boot2container/-/jobs/8517642/artifacts/raw/releases/HEAD/initramfs.linux_amd64.cpio.xz"
EOF

set +x
echo "=========== JOB YAML ================="
cat job.yml
echo "=========== END OF JOB YAML ==========="
set -x

python3 $D/client.py -w run job.yml
job_result=$?

mkdir -pv results
curl -o- http://10.42.0.1:9000/jobs/${CI_JOB_ID}-artifacts.tgz | tar zxf - -C results

exit $job_result
