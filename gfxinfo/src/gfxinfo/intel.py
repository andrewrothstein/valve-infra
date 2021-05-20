SUPPORTED_GPUS = {
    0x3e9b: {
        'gen_version': '9',
        'tags': {"intelgpu:pciid:0x8086:0x3e9b",
                 "intelgpu:family:COFFEELAKE"},
    },
}


class IntelGPU:
    @classmethod
    def from_pciids(cls, pci_vendor_id, pci_device_id, cache_directory):
        if pci_vendor_id != 0x8086:
            return None
        if md := SUPPORTED_GPUS.get(pci_device_id):
            return cls(md)

    def __init__(self, meta):
        self._meta = meta

    @property
    def base_name(self):
        return 'intel' + self._meta['gen_version']

    def tags(self):
        return self._meta['tags']

    def __str__(self):
        from pprint import pformat
        return 'IntelGPU:\n%s' % pformat(self._meta)
