import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

api_root = Path(SPEC).resolve().parent.parent
source_root = api_root / "src"

datas = [
    (str(api_root / "alembic.ini"), "."),
    (str(api_root / "migrations"), "migrations"),
]
binaries = []
hiddenimports = [
    "rapidocr.inference_engine.onnxruntime.main",
    "rapidocr.inference_engine.onnxruntime.provider_config",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "uvicorn.lifespan.off",
    "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
]
# Bento resolves some modules at runtime (e.g. the MTProto runtime via importlib) and watchdog picks
# its observer per platform, so static analysis alone would miss them.
hiddenimports += collect_submodules("bento")
hiddenimports += collect_submodules("watchdog.observers")

for distribution in ("alembic", "bento-api", "fastapi", "pydantic", "sqlalchemy", "uvicorn"):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

try:
    datas += collect_data_files("rapidocr")
except Exception:
    pass

# Smart search model manifest and license notices, read through importlib.resources. Not guarded: a
# bundle without them could neither list nor legally download the embedding models.
datas += collect_data_files("bento.infrastructure.models")

# sqlite-vec (D7): the `vec0` loadable extension is package data that `sqlite_vec.loadable_path()` finds
# next to the module, so it is collected into `sqlite_vec/`. PyInstaller's default patterns only match
# `lib*.so`, hence the explicit ones. Guarded: without the package the spec still builds and search uses
# the Python fallback index.
try:
    if importlib.util.find_spec("sqlite_vec") is not None:
        binaries += collect_dynamic_libs("sqlite_vec", search_patterns=["*.so", "*.dylib", "*.dll"])
        hiddenimports.append("sqlite_vec")
except Exception:
    pass

analysis = Analysis(
    [str(source_root / "bento" / "interfaces" / "desktop" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="bento-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="bento-sidecar",
)
