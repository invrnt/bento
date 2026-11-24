"""Rename extension modules in a wheel to the Android EXT_SUFFIX, optionally fix its version, rewrite RECORD.

usage: fix_ext_suffix.py <wheel> [<version>]

maturin names extensions `*.cpython-313-<arch>-android-android.so`; CPython on Android expects
`*.cpython-313-<triple>.so`. When <version> is given (cryptg's Cargo.toml says 0.1.0), the dist-info
directory, METADATA `Version:` and the wheel file name are rewritten to it.
"""
import base64
import hashlib
import os
import re
import sys
import zipfile

src = sys.argv[1]
version = sys.argv[2] if len(sys.argv) > 2 else None
triple = "aarch64-linux-android" if "arm64" in src else "x86_64-linux-android"
base = os.path.basename(src)
dist, old_version = base.split("-")[:2]
tmp = src + ".tmp"
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    names = {}
    for info in zin.infolist():
        new = re.sub(r"\.cpython-313-[^/]*\.so$", f".cpython-313-{triple}.so", info.filename)
        if version:
            new = new.replace(f"{dist}-{old_version}.dist-info/", f"{dist}-{version}.dist-info/")
        names[info.filename] = new
    record_name = next(n for n in names if n.endswith(".dist-info/RECORD"))
    rows = []
    for old, new in names.items():
        if old == record_name:
            continue
        data = zin.read(old)
        if version and new.endswith(".dist-info/METADATA"):
            data = re.sub(rb"(?m)^Version: .*$", f"Version: {version}".encode(), data, count=1)
        zout.writestr(new, data)
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append(f"{new},sha256={digest},{len(data)}")
    record_new = names[record_name]
    rows.append(f"{record_new},,")
    zout.writestr(record_new, "\n".join(rows) + "\n")
target = src
if version:
    target = os.path.join(os.path.dirname(src), base.replace(f"{dist}-{old_version}-", f"{dist}-{version}-", 1))
os.replace(tmp, target)
if target != src and os.path.exists(src):
    os.remove(src)
