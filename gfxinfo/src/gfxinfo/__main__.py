from . import find_gpu, VulkanInfo

if gpu := find_gpu('/tmp'):
    print(gpu.tags())
    if info := VulkanInfo.construct():
        print(f"vk:vram_size:{info.VRAM_heap.GiB_size}_GiB")
        print(f"vk:gtt_size:{info.GTT_heap.GiB_size}_GiB")

        if info.mesa_version is not None:
            print(f"mesa:version:{info.mesa_version}")
        if info.mesa_git_version is not None:
            print(f"mesa:git:version:{info.mesa_git_version}")

        if info.device_name is not None:
            print(f"vk:device:name:{info.device_name}")

        if info.device_type is not None:
            print(f"vk:device:type:{info.device_type.name}")

        if info.api_version is not None:
            print(f"vk:api:version:{info.driver_name}")

        if info.driver_name is not None:
            print(f"vk:driver:name:{info.driver_name}")
    else:
        print("could not retrieve vulkan info")
else:
    print("No suitable GPU")
