try:
    from functools import cached_property
except:
    from backports.cached_property import cached_property
from enum import Enum

import subprocess
import json
import re


class VulkanExtension:
    def __init__(self, name, version):
        self.name = name
        self.version = version

    def __str__(self):
        return f"<VK extension {self.name} version {self.version}>"

    def __repr__(self):
        return f"{self.__class__}({self.__dict__})"


class VulkanHeap:
    DEVICE_LOCAL_BIT = 0x00000001
    VISIBLE_BIT = 0x00000002
    COHERENT_BIT = 0x00000004
    HOST_CACHED_BIT = 0x00000008
    LAZILY_ALLOCATED_BIT = 0x00000010
    PROTECTED_BIT = 0x00000020
    COHERENT_BIT_AMD = 0x00000040
    UNCACHED_BIT_AMD = 0x00000080

    def __init__(self, size, flags):
        self.size = size
        self.flags = flags
        self.types = []

    def add_type(self, flags):
        self.types.append(flags)

    def has_type(self, flags):
        for t in self.types:
            if flags == t:
                return True
        return False

    @property
    def GiB_size(self):
        return self.size / (1024*1024*1024)


class VulkanDeviceType(Enum):
    OTHER = 0
    INTEGRATED = 1
    DISCRETE = 2
    VIRTUAL = 3
    CPU = 4


class VulkanInfo:
    def __init__(self):
        self.json = json.loads(subprocess.check_output(["vulkaninfo", "--json"]))
        self.summary = subprocess.check_output(["vulkaninfo", "--summary"]).decode()

    @property
    def device(self):
        properties = self.json.get('VkPhysicalDeviceProperties', {})
        return (properties.get("vendorID"), properties.get("deviceID"))

    @property
    def device_name(self):
        properties = self.json.get('VkPhysicalDeviceProperties', {})
        return properties.get("deviceName")

    @cached_property
    def device_type(self):
        properties = self.json.get('VkPhysicalDeviceProperties', {})
        return (VulkanDeviceType(properties.get("deviceType")))

    @cached_property
    def api_version(self):
        properties = self.json.get('VkPhysicalDeviceProperties', {})
        version = int(properties.get("apiVersion"))
        major = version >> 22
        minor = (version >> 12) & 0x3ff
        patch = version & 0xfff
        return '{}.{}.{}'.format(major, minor, patch)

    @cached_property
    def driver_info(self):
        m = re.search(r"driverInfo += (?P<info>.*)\n", self.summary)
        if m:
            return m.groupdict({}).get('info')

    @cached_property
    def driver_name(self):
        m = re.search(r"driverName += (?P<name>.*)\n", self.summary)
        if m:
            return m.groupdict({}).get('name')

    @cached_property
    def mesa_version(self):
        m = re.search(r"Mesa (?P<version>[\w\.\d -]+)", self.driver_info)
        if m:
            return m.groupdict({}).get('version')

    @cached_property
    def mesa_git_version(self):
        m = re.search(r"Mesa [\w\.\d -]+ \(git-(?P<hash>[\da-z]+)\)", self.driver_info)
        if m:
            return m.groupdict({}).get('hash')

    @cached_property
    def conformance_version(self):
        m = re.search(r"conformanceVersion += (?P<version>[\d\.]+)", self.summary)
        if m:
            return m.groupdict({}).get('version')

    @property
    def extensions(self):
        extensions = dict()
        for e in self.json.get('ArrayOfVkExtensionProperties', {}):
            extension = VulkanExtension(name=e['extensionName'], version=e['specVersion'])
            extensions[extension.name] = extension
        return extensions

    @cached_property
    def heaps(self):
        heaps = []

        mem_props = self.json.get("VkPhysicalDeviceMemoryProperties", {})
        for heap in mem_props.get('memoryHeaps', []):
            heaps.append(VulkanHeap(size=heap['size'], flags=heap['flags']))

        for mem_type in mem_props.get('memoryTypes', []):
            heap = heaps[mem_type["heapIndex"]]
            heap.add_type(mem_type["propertyFlags"])

        return heaps

    @cached_property
    def VRAM_heap(self):
        for heap in self.heaps:
            if heap.has_type(VulkanHeap.DEVICE_LOCAL_BIT):
                return heap
        return VulkanHeap(size=0, flags=-1)

    @cached_property
    def GTT_heap(self):
        for heap in self.heaps:
            if heap.has_type(VulkanHeap.VISIBLE_BIT | VulkanHeap.COHERENT_BIT):
                return heap
        return VulkanHeap(size=0, flags=-1)


if __name__ == '__main__':
    info = VulkanInfo()

    print(f"The device {info.device} (VRAM={info.VRAM_heap.GiB_size} GiB, GTT={info.GTT_heap.GiB_size} GiB) implements {len(info.extensions)} extensions")
