"""CPU cores and physical RAM of this machine, read with the standard library only.

Used by the smart search onboarding suggestion (D8, `domain.smart_search.suggest_in_onboarding`). A value that
cannot be read is 0, which never suggests anything.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class HostResources:
    cpu_cores: int
    ram_bytes: int


@lru_cache(maxsize=1)
def host_resources() -> HostResources:
    return HostResources(cpu_cores=os.cpu_count() or 0, ram_bytes=physical_ram_bytes())


def physical_ram_bytes() -> int:
    if sys.platform == "win32":
        return _windows_ram_bytes()
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return 0
    if pages <= 0 or page_size <= 0:
        return 0
    return int(pages) * int(page_size)


def _windows_ram_bytes() -> int:
    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0
    except (AttributeError, OSError):
        return 0
    return int(status.ullTotalPhys)
