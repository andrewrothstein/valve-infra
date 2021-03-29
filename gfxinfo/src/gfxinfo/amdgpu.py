import requests
import re

class AMDGPU:
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

            # RDNA 2amdgpu_supported_gpus
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

    def __repr__(self):
        return str(self)

    @classmethod
    def download_pciid_db(self):
        url = "https://cgit.freedesktop.org/~agd5f/linux/plain/drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c?h=amd-staging-drm-next"
        r = requests.get(url)
        r.raise_for_status()
        return r.text

    @classmethod
    def supported_gpus(cls, amdgpu_drv_path=None):
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
                    pciid = cls(line)
                    pciids[(pciid.vendor_id, pciid.product_id)] = pciid
                except ValueError:
                    continue

        return pciids

if __name__ == '__main__':
    print(AMDGPU.supported_gpus())
