"""Rename extension modules in a wheel to the Android EXT_SUFFIX and rewrite RECORD."""
import base64, hashlib, re, sys, zipfile, os
src = sys.argv[1]
triple = "aarch64-linux-android" if "arm64" in src else "x86_64-linux-android"
tmp = src + ".tmp"
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    names = {}
    for info in zin.infolist():
        new = re.sub(r"\.cpython-313-[^/]*\.so$", f".cpython-313-{triple}.so", info.filename)
        names[info.filename] = new
    record_name = next(n for n in names if n.endswith(".dist-info/RECORD"))
    rows = []
    for old, new in names.items():
        if old == record_name:
            continue
        data = zin.read(old)
        zout.writestr(new, data)
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append(f"{new},sha256={digest},{len(data)}")
    rows.append(f"{record_name},,")
    zout.writestr(record_name, "\n".join(rows) + "\n")
os.replace(tmp, src)
