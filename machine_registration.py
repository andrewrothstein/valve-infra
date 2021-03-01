#!/usr/bin/env python3

from functools import cached_property
from collections import namedtuple
import netifaces
import argparse
import requests
import psutil
import sys
import re
import os


class AMDPciId:
    def __init__(self, pciid_line):
        m = re.match(r"^\s*{(?P<vendor_id>0x[\da-fA-F]+),\s*(?P<product_id>0x[\da-fA-F]+),\s*PCI_ANY_ID,\s*PCI_ANY_ID,\s*0,\s*0,\s*(?P<flags>.*)},\s*$", pciid_line)

        if m is None:
            raise ValueError("The line is not a valid PCIID line")

        groups = m.groupdict()
        self.vendor_id = int(groups['vendor_id'], 0)
        self.product_id = int(groups['product_id'], 0)
        self.codename = "UNKNOWN"
        self.is_APU = False
        self.is_Mobility = False

        # Parse the codename and flags
        flags = [f.strip() for f in groups['flags'].split('|')]
        for flag in flags:
            if flag.startswith("CHIP_"):
                self.codename = flag[5:]
            elif flag == "AMD_IS_APU":
                self.is_APU = True
            elif flag == "AMD_IS_MOBILITY":
                self.is_Mobility = True
            else:
                print(f"WARNING: Unknown flag '{flag}'")

        if self.architecture is None:
            print(f"{self.codename}: Unknown architecture", file=sys.stderr)
        if self.family is None:
            print(f"{self.codename}: Unknown family", file=sys.stderr)
        if self.gfx_version is None:
            print(f"{self.codename}: Unknown GFX version", file=sys.stderr)

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

            # Unknowns (not interested in getting a message for them)
            "MULLINS": "UK",
            "TOPAZ": "UK",
            "SIENNA_CICHLID": "UK",
            "VANGOGH": "UK",
            "NAVY_FLOUNDER": "UK",
            "DIMGREY_CAVEFISH": "UK",
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

            # Navi / RDNA1
            "NAVI10": "RDNA1",
            "NAVI12": "RDNA1",
            "NAVI14": "RDNA1",

            # RDNA 2
            "SIENNA_CICHLID": "RDNA2",
            "VANGOGH": "RDNA2",
            "NAVY_FLOUNDER": "RDNA2",
            "DIMGREY_CAVEFISH": "RDNA2",  # WARNING: Based on leaks
        }

        return architectures.get(self.codename)

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

            # GFX10
            "RDNA1": "gfx10",
            "RDNA2": "gfx10",
        }

        return versions.get(self.architecture)

    @property
    def pciid(self):
        return f"{hex(self.vendor_id)}:{hex(self.product_id)}"

    def __str__(self):
        return f"<PCIID {self.pciid} - {self.codename} - {self.family} - {self.architecture} - {self.gfx_version.lower()}>"

    @classmethod
    def download_pciid_db(self):
        url = "https://cgit.freedesktop.org/~agd5f/linux/plain/drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c?h=amd-staging-drm-next"
        r = requests.get(url)
        r.raise_for_status()
        return r.text

    @classmethod
    def amdgpu_supported_gpus(cls, amdgpu_drv_path=None):
        pciids = dict()

        if amdgpu_drv_path:
            drv = open(amdgpu_drv_path, 'r').read()
        else:
            drv = cls.download_pciid_db()

        started = False
        for line in drv.splitlines():
            if not started:
                if line == "static const struct pci_device_id pciidlist[] = {":
                    started = True
                    continue
            else:
                if line == "	{0, 0, 0}":
                    break

                try:
                    pciid = AMDPciId(line)
                    pciids[(pciid.vendor_id, pciid.product_id)] = pciid
                except ValueError:
                    continue

        return pciids


NetworkConf = namedtuple("NetworkConf", ['mac', 'ipv4', 'ipv6'])


class MachineInfo:
    @cached_property
    def pci_devices(self):
        devices = open('/proc/bus/pci/devices').readlines()
        ids = [l.split('\t')[1] for l in devices]
        return [(int(id[:4], 16), int(id[4:], 16)) for id in ids]

    @cached_property
    def plugged_amd_gpus(self):
        amdgpu_pciids = AMDPciId.amdgpu_supported_gpus(self.amdgpu_drv_path)
        plugged_amd_gpus = set(self.pci_devices).intersection(set(amdgpu_pciids.keys()))
        return [amdgpu_pciids[g] for g in plugged_amd_gpus]

    def __init__(self, amdgpu_drv_path=None):
        self.amdgpu_drv_path = amdgpu_drv_path

    def print_topology(self):
        print(f"# {len(plugged_amd_gpus)} amdgpu-compatible GPUs:")
        for amd_gpu in plugged_amd_gpus:
            print(amdgpu_pciids[amd_gpu])
        print()

    @cached_property
    def amdgpu(self):
        # Check the configuration is supported
        if len(self.plugged_amd_gpus) != 1:
            raise ValueError("ERROR: A single amdgpu-compatible GPU is required for test machines")
        return list(self.plugged_amd_gpus)[0]

    @property
    def machine_base_name(self):
        return self.amdgpu.gfx_version.lower()

    @cached_property
    def machine_tags(self):
        tags = set()

        tags.add(f"amdgpu:family::{self.amdgpu.family}")
        tags.add(f"amdgpu:codename::{self.amdgpu.codename}")
        tags.add(f"amdgpu:gfxversion::{self.amdgpu.gfx_version}")

        if self.amdgpu.is_APU:
            tags.add("amdgpu:APU")

        return tags

    @property
    def default_gateway_nif_addrs(self):
        _, gw_nif = netifaces.gateways().get('default', {}).get(netifaces.AF_INET, (None, None))

        addrs = netifaces.ifaddresses(gw_nif)
        mac = addrs[netifaces.AF_LINK][0]['addr']
        ipv4 = addrs.get(netifaces.AF_INET, [{}])[0].get('addr')
        ipv6 = addrs.get(netifaces.AF_INET6, [{}])[0].get('addr')

        return NetworkConf(mac, ipv4, ipv6)

    def to_machine_registration_request(self):
        addrs = self.default_gateway_nif_addrs
        return {
            "base_name": self.machine_base_name,
            "tags": list(self.machine_tags),

            "mac_address": addrs.mac,
            "ip_address": addrs.ipv4,
        }

parser = argparse.ArgumentParser()
parser.add_argument('-a', dest='amdgpu_drv_path', default=None,
                    help='Path to an up-to-date amdgpu_drv.c file')
parser.add_argument('-m', '--mars_host', dest='mars_host', default="10.42.0.1",
                    help='URL to the machine registration service MaRS')
parser.add_argument('action', help='Action this script should do',
                    choices=['register', 'cache_dbs', 'check'])
args = parser.parse_args()

info = MachineInfo(amdgpu_drv_path=args.amdgpu_drv_path)
if args.action == "register":
    params = info.to_machine_registration_request()

    r = requests.post(f"http://{args.mars_host}/api/v1/machine/", json=params)
    if r.status_code == 400:
        mac_address = params['mac_address']
        r = requests.patch(f"http://{args.mars_host}/api/v1/machine/{mac_address}/", json=params)
        r.raise_for_status()

elif args.action == "cache_dbs":
    if args.amdgpu_drv_path is None:
        print("ERROR: Please set the amdgpu_drv_path (-a)", file=sys.stderr)
        sys.exit(1)

    with open(args.amdgpu_drv_path, 'w') as f:
        f.write(AMDPciId.download_pciid_db())

elif args.action == "check":
    mac_addr = info.default_gateway_nif_addrs.mac

    # Get the expected configuration
    r = requests.get(f"http://{args.mars_host}/api/v1/machine/{mac_addr}/")
    r.raise_for_status()
    expected_conf = r.json()

    # Generate the configuration
    local_config = info.to_machine_registration_request(ignore_local_tty_device=True)
    has_differences = False
    for key, value in local_config.items():
        expected_value = expected_conf.get(key)
        if (type(expected_value) != type(value) or \
            (type(value) is list and set(expected_value) != set(value)) or \
            (type(value) is not list and expected_value != value)):
            has_differences = True
            print(f"Mismatch for '{key}': {value} vs the expected {expected_value}")

    if not has_differences:
        print("No differences found!")

    sys.exit(0 if has_differences else 1)
