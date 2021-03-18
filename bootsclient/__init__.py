#!/bin/env python3

from enum import Enum

import requests
import time


class BootsTaskStatus(Enum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    FINISHED = "finished"

class BootsTask:
    def __init__(self, name, task_url):
        self.name = name
        self.task_url = task_url

        self.state = BootsTaskStatus.UNKNOWN
        self.msg = "initial"

        self.update()

    def update(self):
        if self.is_finished:
            return

        r = requests.get(self.task_url)
        r.raise_for_status()

        data = r.json()
        self.state = BootsTaskStatus(data.get("state", BootsTaskStatus.UNKNOWN.value))
        self.msg = data.get("message")

    @property
    def is_finished(self):
        return self.state == BootsTaskStatus.FINISHED

    def __str__(self):
        return f"<{self.name}({self.msg})>"


class BootsClient:
    def __init__(self, boots_url):
        self.boots_url = boots_url

    def url(self, path):
        return f"{self.boots_url}{path}"

    def _download_file(self, name, url):
        params = {
            "path": url,
            "name": name,
            "overwrite": True,
        }

        r = requests.post(self.url("/kernels/download"), json=params)
        r.raise_for_status()

        return BootsTask(name, r.json().get('link'))

    def download_kernel(self, name, url):
        return self._download_file(name, url)

    def download_initramfs(self, name, url):
        return self._download_file(name, url)

    def set_config(self, mac_addr, kernel_path, initramfs_path, kernel_cmdline, rootfs_path=None):
        params = {
            "method": "b2c",
            "initrd_path": initramfs_path,
            "kernel_path": kernel_path,
            "cmdline": kernel_cmdline,
        }

        r = requests.post(self.url(f"/duts/{mac_addr}/boot"), json=params)
        return r.status_code == 200
