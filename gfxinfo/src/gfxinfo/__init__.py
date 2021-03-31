from functools import cached_property

from .amdgpu import AMDGPU
from .vulkan import VulkanInfo


class GFXInfo:
    def __init__(self, amdgpu_drv_path=None):
        self.amdgpu_drv_path = amdgpu_drv_path

    def print_topology(self):
        print(f"# {len(self.plugged_amd_gpus)} amdgpu-compatible GPUs:")
        for amd_gpu in self.plugged_amd_gpus:
            print(amdgpu_pciids[amd_gpu])
        print()

    @cached_property
    def pci_devices(self):
        devices = open('/proc/bus/pci/devices').readlines()
        ids = [l.split('\t')[1] for l in devices]
        return [(int(id[:4], 16), int(id[4:], 16)) for id in ids]

    @cached_property
    def plugged_amd_gpus(self):
        amdgpu_pciids = AMDGPU.supported_gpus(self.amdgpu_drv_path)
        plugged_amd_gpus = set(self.pci_devices).intersection(set(amdgpu_pciids.keys()))
        return [amdgpu_pciids[g] for g in plugged_amd_gpus]

    @cached_property
    def amdgpu(self):
        # Check the configuration is supported
        if len(self.plugged_amd_gpus) != 1:
            raise ValueError("ERROR: A single amdgpu-compatible GPU is required for test machines")
        return list(self.plugged_amd_gpus)[0]

    def machine_tags(self):
        tags = set()

        tags.add(f"amdgpu:pciid:{self.amdgpu.pciid}")
        tags.add(f"amdgpu:family:{self.amdgpu.family}")
        tags.add(f"amdgpu:codename:{self.amdgpu.codename}")
        tags.add(f"amdgpu:architecture:{self.amdgpu.architecture}")
        tags.add(f"amdgpu:gfxversion:{self.amdgpu.gfx_version}")

        if self.amdgpu.is_APU:
            tags.add("amdgpu:APU")

        try:
            info = VulkanInfo()

            tags.add(f"amdgpu:vram_size:{info.VRAM_heap.GiB_size}_GiB")
            tags.add(f"amdgpu:gtt_size:{info.GTT_heap.GiB_size}_GiB")

            if info.mesa_version is not None:
                tags.add(f"mesa:version:{info.mesa_version}")

            if info.mesa_git_version is not None:
                tags.add(f"mesa:git:version:{info.mesa_git_version}")

            if info.device_name is not None:
                tags.add(f"vk:device:name:{info.device_name}")

            if info.device_type is not None:
                tags.add(f"vk:device:type:{info.device_type.name}")

            if info.api_version is not None:
                tags.add(f"vk:api:version:{info.driver_name}")


            if info.driver_name is not None:
                tags.add(f"vk:driver:name:{info.driver_name}")
        except Exception as e:
            print(e)

        return tags

if __name__ == '__main__':
    print(GFXInfo().machine_tags())
