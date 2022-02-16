from dataclasses import dataclass

from .amdgpu import AmdGpuDeviceDB
from .intel import IntelGpuDeviceDB
from .virt import VirtIOGpuDeviceDB
from .gfxinfo_vulkan import VulkanInfo


SUPPORTED_GPU_DBS = [AmdGpuDeviceDB(), IntelGpuDeviceDB(), VirtIOGpuDeviceDB()]


@dataclass
class PCIDevice:
    vendor_id: int
    product_id: int
    revision: int

    @classmethod
    def from_str(cls, pciid):
        fields = pciid.split(":")
        if len(fields) not in [2, 3]:
            raise ValueError("The pciid '{pciid}' is invalid. Format: xxxx:xxxx[:xx]")

        revision = 0 if len(fields) == 2 else int(fields[2], 16)
        return cls(vendor_id=int(fields[0], 16),
                   product_id=int(fields[1], 16),
                   revision=revision)


def pci_devices():
    def pciid(pci_id, rev):
        return PCIDevice(vendor_id=int(pci_id[:4], 16),
                         product_id=int(pci_id[4:], 16),
                         revision=int(rev, 16))

    devices = open('/proc/bus/pci/devices').readlines()
    ids = [line.split('\t')[1:3] for line in devices]
    return [pciid(pci_id, rev) for pci_id, rev in ids]


def find_gpu():
    """For now we only support single-gpu DUTs"""
    devices = pci_devices()

    for pci_device in devices:
        for gpu_db in SUPPORTED_GPU_DBS:
            if gpu := gpu_db.from_pciid(pci_device):
                return gpu

    # We could not find the GPU in our databases, update them
    for gpu_db in SUPPORTED_GPU_DBS:
        gpu_db.update()

    # Retry, now that we have updated our DBs
    for pci_device in devices:
        for gpu_db in SUPPORTED_GPU_DBS:
            if gpu := gpu_db.from_pciid(pci_device):
                return gpu


def cache_db():
    for gpu_db in SUPPORTED_GPU_DBS:
        gpu_db.cache_db()


__all__ = ['pci_devices', 'find_gpu', 'cache_db', 'VulkanInfo']
