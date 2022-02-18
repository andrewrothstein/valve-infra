from dataclasses import dataclass
import os

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
    def readfile(root, filename):
        with open(os.path.join(root, filename)) as f:
            return f.read().strip()

    pciids = []
    for root, dirs, files in os.walk('/sys/devices/'):
        if root == "/sys/devices/":
            dirs[0:] = [d for d in dirs if d.startswith("pci")]

        if set(["vendor", 'device', 'revision']).issubset(files):
            pci_dev = PCIDevice(vendor_id=int(readfile(root, "vendor"), 16),
                                product_id=int(readfile(root, "device"), 16),
                                revision=int(readfile(root, "revision"), 16))
            pciids.append(pci_dev)

    return pciids


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


def find_gpu_from_pciid(pciid):
    for gpu_db in SUPPORTED_GPU_DBS:
        if gpu := gpu_db.from_pciid(pciid):
            return gpu

    # We could not find the GPU, retry with updated DBs
    for gpu_db in SUPPORTED_GPU_DBS:
        gpu_db.update()
        if gpu := gpu_db.from_pciid(pciid):
            return gpu


__all__ = ['pci_devices', 'find_gpu', 'cache_db', 'VulkanInfo']
