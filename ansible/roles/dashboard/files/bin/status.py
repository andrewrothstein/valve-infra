#!/usr/bin/env python3
import os
import sys
import subprocess
import time

yellow = "\u001b[33m"
green = "\u001b[32m"
red = "\u001b[31m"
normal = "\u001b[37m"


def show_status(serv):

    status = subprocess.getoutput(f"systemctl is-active {serv}")
    expected = "active"

    if ":" in serv:
        serv, expected = serv.split(":")

    if status == "activating":
        color = yellow
    elif status == expected:
        color = green
        status = "OK"
    else:
        color = red

    return f"{serv: <18} {color} {status} {normal}"


def show_nic(nic):
    sysfs = f"/sys/class/net/{nic}"

    if not os.path.isdir(sysfs):
        return f"{red}{nic} does not exists!{normal}"

    with open(f"{sysfs}/operstate") as f:
        status = f.read().strip()

    ip = subprocess.getoutput(f"ip a show {nic} | grep -e 'inet\s' |tr -s ' ' | cut -d' ' -f3")

    if status == "unknown":
        status = "???"
        color = yellow
    elif status == "up":
        color = green
    else:
        color = red

    return f"{nic: <8} {color} {status: <4} {ip} {normal}"


networking_list = ["private", "wg0"]
services_list = sys.argv[1:]

while True:
    os.system("clear")
    print("\nNetworking\n")

    for e in networking_list:
        print(show_nic(e))

    print("\nServices\n")

    for e in services_list:
        print(show_status(e))

    time.sleep(2)
