import os
from typing import Dict


def job_environment_vars() -> Dict[str, str]:  # pragma: nocover
    """Return environment variables useful for job submission as a
    dictionary."""
    return {
        k: os.environ[k] for k in [
            'MINIO_URL',
            'FDO_PROXY_REGISTRY',
            'LOCAL_REGISTRY',
        ]
    }
