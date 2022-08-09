#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.request


def Blue(text):
    return f"{chr(27)}[34m {text}{chr(27)}[00m"
def Green(text):
    return f"{chr(27)}[92m {text}{chr(27)}[00m"
def Yellow(text):
    return f"{chr(27)}[93m {text}{chr(27)}[00m"
def Red(text):
    return f"{chr(27)}[91m {text}{chr(27)}[00m"

def main():
    while True:
        machines = None
        # clear terminal
        print(f"{chr(27)}[2J", end="")
        # start printing at top
        print(f"{chr(27)}[H", end="")

        # header / title
        term_cols = os.get_terminal_size()[0]
        print(f"{'Machines' : ^{term_cols}}")

        try:
            with urllib.request.urlopen('http://localhost/api/v1/machines') as resp:
                machines = json.loads(resp.read())

        except urllib.error.URLError:
            # status printed to screen later
            pass

        if not machines or "machines" not in machines:
            print(Red("Unable to get list of machines!"))
            time.sleep(1)
            continue

        for mac, machine in machines["machines"].items():
            state = machine["state"]
            ready = machine["ready_for_service"]
            status = None
            if not ready:
                if machine["state"] == "TRAINING":
                    status = Blue(machine["state"])
                else:
                    status = Yellow(machine["state"])
            else:
                status = Green(machine["state"])
            label = f"{machine['base_name']} ({machine['ip_address']}) ({machine['pdu']['name']}/{machine['pdu']['port_id']})"
            print(f"{label:<30}{status}")

        time.sleep(2)

if __name__ == "__main__":
    sys.exit(main())
