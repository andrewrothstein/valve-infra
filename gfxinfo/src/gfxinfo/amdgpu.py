from functools import cache
from typing import Dict, Tuple
import json
import os
import re
import requests
import sys
try:
    from functools import cached_property
except:
    from backports.cached_property import cached_property


def build_cache_filename(cache_directory):
    return os.path.join(cache_directory, 'amdgpu_drv.c')


@cache
def download_supported_pci_devices(cache_directory):
    cache_filename = build_cache_filename(cache_directory)
    try:
        with open(cache_filename, 'r') as f:
            return f.read()
    except:
        # Fetch from the network below in case the cache isn't prepared.
        pass

    url = "https://gitlab.freedesktop.org/agd5f/linux/-/raw/amd-staging-drm-next/drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c"
    r = requests.get(url)
    r.raise_for_status()

    drv = r.text
    # It would be nice to cache the the results of parsing as well,
    # but that requires more changes to the class designs, since
    # they're not JSON serializable currently, and pickling is
    # documented as unsafe for untrusted inputs.
    with open(cache_filename, 'w') as f:
        f.write(drv)
    return drv


def parse_pci_devices(cache_directory):
    pci_devices: Dict[Tuple[str, str], AMDGPU] = dict()

    drv = download_supported_pci_devices(cache_directory)

    comp_re = re.compile(
        r"^\s*{(?P<vendor_id>0x[\da-fA-F]+),\s*(?P<product_id>0x[\da-fA-F]+),"
        r"\s*PCI_ANY_ID,\s*PCI_ANY_ID,\s*0,\s*0,\s*(?P<flags>.*)},\s*$")

    started = False
    for line in drv.splitlines():
        if not started:
            if line == "static const struct pci_device_id pciidlist[] = {":
                started = True
                continue
        else:
            if line == "	{0, 0, 0}":
                break

            if m := comp_re.match(line):
                try:
                    vendor_id = int(m.group('vendor_id'), 0)
                    product_id = int(m.group('product_id'), 0)
                    flags = m.group('flags') or None
                    key = vendor_id << 16 | product_id
                    pci_devices[key] = \
                        AMDGPU(vendor_id, product_id, flags)
                except ValueError:
                    continue

    return pci_devices


class AMDGPU:
    @classmethod
    def from_pciids(cls, pci_vendor_id, pci_device_id, cache_directory):
        if pci_vendor_id != 0x1002:
            return None
        supported_devices = parse_pci_devices(cache_directory)
        return supported_devices.get(pci_vendor_id << 16 | pci_device_id, None)

    def __init__(self, vendor_id: int, product_id: int, flags: str):
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.amdgpu_codename = "UNKNOWN"
        self.is_APU = False
        self.is_Mobility = False
        self.has_experimental_support = False

        for flag in [f.strip() for f in flags.split('|')]:
            if flag.startswith("CHIP_"):
                self.amdgpu_codename = flag[5:]
            elif flag == "AMD_IS_APU":
                self.is_APU = True
            elif flag == "AMD_IS_MOBILITY":
                self.is_Mobility = True
            elif flag == "AMD_EXP_HW_SUPPORT":
                self.has_experimental_support = True
            else:
                print(f"WARNING: Unknown flag '{flag}'")

        if self.architecture is None:
            print(f"{self.amdgpu_codename}: Unknown architecture", file=sys.stderr)
        if self.family is None:
            print(f"{self.amdgpu_codename}: Unknown family", file=sys.stderr)
        if self.gfx_version is None:
            print(f"{self.amdgpu_codename}: Unknown GFX version", file=sys.stderr)

    @property
    def codename(self):
        codenames = {
            "SIENNA_CICHLID": "NAVI21",
            "NAVY_FLOUNDER": "NAVI22",
            "DIMGREY_CAVEFISH": "NAVI23",
        }

        return codenames.get(self.amdgpu_codename, self.amdgpu_codename)

    @property
    def family(self):
        families = {
            # SI
            "TAHITI": "SI",
            "PITCAIRN": "SI",
            "VERDE": "SI",
            "OLAND": "SI",
            "HAINAN": "SI",

            # CI
            "BONAIRE": "CI",
            "HAWAII": "CI",
            "KAVERI": "CI",

            # KV
            "KABINI": "KV",

            # VI
            "TONGA": "VI",
            "FIJI": "VI",
            "POLARIS10": "VI",
            "POLARIS11": "VI",
            "POLARIS12": "VI",
            "VEGAM": "VI",

            # CZ
            "CARRIZO": "CZ",
            "STONEY": "CZ",

            # AI
            "VEGA10": "AI",
            "VEGA12": "AI",
            "VEGA20": "AI",
            "ARCTURUS": "AI",

            # RV
            "RAVEN": "RV",
            "RENOIR": "RV",

            # NV
            "NAVI10": "NV",
            "NAVI12": "NV",
            "NAVI14": "NV",

            # Unknowns
            "MULLINS": "UNK",
            "TOPAZ": "UNK",
            "NAVI21": "UNK",
            "VANGOGH": "UNK",
            "NAVI22": "UNK",
            "NAVI23": "UNK",
            "ALDEBARAN": "UNK",
        }

        return families.get(self.codename)

    @property
    def architecture(self):
        architectures = {
            # GCN1
            "TAHITI": "GCN1",
            "PITCAIRN": "GCN1",
            "VERDE": "GCN1",
            "OLAND": "GCN1",
            "HAINAN": "GCN1",

            # GCN2
            "KAVERI": "GCN2",
            "BONAIRE": "GCN2",
            "HAWAII": "GCN2",
            "KABINI": "GCN2",
            "MULLINS": "GCN2",

            # GCN3
            "TOPAZ": "GCN3",
            "TONGA": "GCN3",
            "FIJI": "GCN3",
            "CARRIZO": "GCN3",
            "STONEY": "GCN3",

            # GCN4
            "POLARIS10": "GCN4",
            "POLARIS11": "GCN4",
            "POLARIS12": "GCN4",
            "VEGAM": "GCN4",

            # GCN5
            "VEGA10": "GCN5",
            "VEGA12": "GCN5",
            "RAVEN": "GCN5",

            # GCN5.1
            "VEGA20": "GCN5.1",
            "RENOIR": "GCN5.1",

            # CDNA
            "ARCTURUS": "CDNA",

            # CDNA2
            "ALDEBARAN": "CDNA2",

            # Navi / RDNA1
            "NAVI10": "RDNA1",
            "NAVI12": "RDNA1",
            "NAVI14": "RDNA1",

            # RDNA2
            "NAVI21": "RDNA2",
            "NAVI22": "RDNA2",
            "NAVI23": "RDNA2",
            "VANGOGH": "RDNA2",
        }

        return architectures.get(self.codename)

    @property
    def base_name(self):
        return self.gfx_version

    @property
    def gfx_version(self):
        versions = {
            # GFX7
            "GCN1": "gfx6",

            # GFX7
            "GCN2": "gfx7",

            # GFX8
            "GCN3": "gfx8",
            "GCN4": "gfx8",

            # GFX9
            "GCN5": "gfx9",
            "GCN5.1": "gfx9",
            "CDNA": "gfx9",
            "CDNA2": "gfx9",

            # GFX10
            "RDNA1": "gfx10",
            "RDNA2": "gfx10",
        }

        return versions.get(self.architecture)

    def tags(self):
        tags = set()

        tags.add(f"amdgpu:pciid:{self.pciid}")
        tags.add(f"amdgpu:family:{self.family}")
        tags.add(f"amdgpu:codename:{self.codename}")
        tags.add(f"amdgpu:architecture:{self.architecture}")
        tags.add(f"amdgpu:gfxversion:{self.gfx_version}")
        if self.is_APU:
            tags.add("amdgpu:APU")
        if self.has_experimental_support:
            tags.add("amdgpu:EXP_HW_SUPPORT")

        return tags

    @property
    def pciid(self):
        return f"{hex(self.vendor_id)}:{hex(self.product_id)}"

    def __str__(self):
        return f"<AMDGPU: PCIID {self.pciid} - {self.codename} - {self.family} - {self.architecture} - {self.gfx_version.lower()}>"

    def __repr__(self):
        return f"{self.__class__}({self.__dict__})"
