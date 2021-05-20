import requests
import re
import sys
try:
    from functools import cached_property
except:
    from backports.cached_property import cached_property
from functools import cache
from typing import Dict, Tuple


SUPPORTED_GPUS = {
    0x1050: {
        'tags': {"virtio:pciid:0x1af4:0x1050",
                 "virtgpu:family:VIRTIO"},
    },
}


class VirtGPU:
    @classmethod
    def from_pciids(cls, pci_vendor_id, pci_device_id, cache_directory):
        if pci_vendor_id != 0x1af4:
            return None
        if md := SUPPORTED_GPUS.get(pci_device_id):
            return cls(md)

    def __init__(self, meta):
        self._meta = meta

    @property
    def base_name(self):
        return 'virtio'

    def tags(self):
        return self._meta['tags']

    def __str__(self):
        from pprint import pformat
        return 'VirtGPU:\n%s' % pformat(self._meta)
