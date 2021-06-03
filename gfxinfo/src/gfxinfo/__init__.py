from .amdgpu import AMDGPU
from .intel import IntelGPU
from .virt import VirtGPU
from .gfxinfo_vulkan import VulkanInfo

SUPPORTED_GPUS = [AMDGPU, IntelGPU, VirtGPU]

def pci_devices():
    devices = open('/proc/bus/pci/devices').readlines()
    ids = [line.split('\t')[1] for line in devices]
    return [(int(id[:4], 16), int(id[4:], 16)) for id in ids]


def find_gpu(cache_directory='/tmp'):
    """For now we only support single-gpu DUTs"""
    for pci_device in pci_devices():
        for gpu in SUPPORTED_GPUS:
            if gpu := gpu.from_pciids(*pci_device, cache_directory):
                return gpu
