#!/bin/bash

# Quick n' dirty manual test script to ensure BIOS and UEFI systems
# boot at least on QEMU, this is no guarantee they'll boot in the wild
# though, but better than nothing

# TODO: Get CI working, run QEMU in the background, monitor the log
# file, check iPXE started booting in both MBR and UEFI...

set -o nounset
set -o pipefail
set -o xtrace

OUTPUT_ISO=$1
BOOT_MODE=${2:-MBR}
SSH_LOCAL_PORT=${3:-}

PRIV_MAC=$(printf "DE:AD:BE:EF:%02X:%02X\n" $((RANDOM%256)) $((RANDOM%256)))
PUBLIC_MAC=$(printf "DE:AD:BE:EF:%02X:%02X\n" $((RANDOM%256)) $((RANDOM%256)))

if [ -n "$SSH_LOCAL_PORT" ]; then
    PUBLIC_NIC="-device virtio-net-pci,romfile=,netdev=net0,mac=${PUBLIC_MAC} -netdev user,id=net0,hostfwd=tcp::${SSH_LOCAL_PORT}-:22"
else
    PUBLIC_NIC="-nic user,mac=${PUBLIC_MAC},model=virtio-net-pci,ipv6=off"
fi

if [ "$BOOT_MODE" = "UEFI" ]; then
    __ovmf_dirs=("/usr/share/edk2-ovmf/x64" "/usr/share/OVMF")
    __ovmf=
    for d in "${__ovmf_dirs[@]}"; do
	[ -e "$d/OVMF.fd" ] && __ovmf="$d/OVMF.fd"
    done

    if [ -z "$__ovmf" ] ; then
	echo "ERROR: OVMF not found. Probably missing the edk2 ovmf packages."
	exit 1
    fi

    BOOT_MODE="-drive if=pflash,format=raw,unit=0,file=$__ovmf,readonly=on -global driver=cfi.pflash01,property=secure,value=off"
elif [ "$BOOT_MODE" = "MBR" ]; then
    BOOT_MODE=
else
    echo "Unknown boot mode"
    exit 1
fi

# BIOS boot check
# TODO: daemonize, wait a bit, check serial1.log for success condition
qemu-system-x86_64 \
    -enable-kvm \
    -display none -serial stdio \
    $BOOT_MODE \
    -m size=4096 \
    -k en \
    -device virtio-scsi-pci,id=scsi0 \
    -device scsi-cd,bus=scsi0.0,drive=cdrom0 \
    -drive id=cdrom0,if=none,format=raw,media=cdrom,readonly=on,file="$OUTPUT_ISO" \
    -display gtk -vga std \
    $PUBLIC_NIC \
    -nic none,mac="$PRIV_MAC",model=virtio-net-pci \
    -boot d -no-reboot
