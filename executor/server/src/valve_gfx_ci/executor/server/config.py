import os
from typing import Dict

BASE_DIR = os.path.dirname(__file__)


def template(filename):
    return os.path.join(os.path.join(BASE_DIR, 'templates'), filename)


def job_template(filename):
    return os.path.join(os.path.join(BASE_DIR, 'job_templates'), filename)


configurables = {
    'EXECUTOR_HOST': '0.0.0.0',
    'EXECUTOR_PORT': 80,
    'EXECUTOR_REGISTRATION_JOB': job_template('register.yml.j2'),
    'EXECUTOR_BOOTLOOP_JOB': job_template('bootloop.yml.j2'),
    'EXECUTOR_VPDU_ENDPOINT': None,
    'SERGENT_HARTMAN_BOOT_COUNT': '100',
    'SERGENT_HARTMAN_QUALIFYING_BOOT_COUNT': '100',
    'SERGENT_HARTMAN_REGISTRATION_RETRIAL_DELAY': '120',
    'GITLAB_URL': 'https://gitlab.freedesktop.org',
    'GITLAB_CONF_FILE': '/mnt/tmp/gitlab-runner/config.toml',
    'GITLAB_CONF_TEMPLATE_FILE': template('gitlab_runner_config.toml.j2'),
    'FARM_NAME': None,
    'MARS_DB_FILE': '/app/config/mars.yaml',
    'SALAD_URL': 'http://ci-gateway:8005',
    'BOOTS_ROOT': '/mnt/tmp/boots',
    'BOOTS_TFTP_ROOT': '/mnt/tmp/boots/tftp',
    'BOOTS_DISABLE_DNSMASQ': None,
    'MINIO_URL': 'http://ci-gateway:9000',
    'MINIO_ROOT_USER': 'minioadmin',
    'MINIO_ROOT_PASSWORD': 'minio-root-password',
    'MINIO_ADMIN_ALIAS': 'local',
    'PRIVATE_INTERFACE': 'private',
    'BOOTS_DEFAULT_KERNEL': 'http://ci-gateway:9000/boot/default_kernel',
    'BOOTS_DEFAULT_INITRD': 'http://ci-gateway:9000/boot/default_boot2container.cpio.xz',
    'BOOTS_DEFAULT_CMDLINE': 'b2c.container="-ti --tls-verify=false docker://ci-gateway:8002/mupuf/valve-infra/machine_registration:latest register" b2c.ntp_peer="ci-gateway" b2c.cache_device=none loglevel=6'  # noqa
}

__all__ = []


for config_option, default in configurables.items():
    globals()[config_option] = os.environ.get(config_option,
                                              default)
    __all__.append(config_option)


def job_environment_vars() -> Dict[str, str]:  # pragma: nocover
    """Return environment variables useful for job submission as a
    dictionary."""

    ret = {
        'MINIO_URL': globals()['MINIO_URL'],
    }

    for var, val in os.environ.items():
        if var.startswith('EXECUTOR_JOB__'):
            ret[var.lstrip('EXECUTOR_JOB__')] = val

    return ret
