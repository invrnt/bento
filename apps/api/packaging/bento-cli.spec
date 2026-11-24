# Standalone `bento` CLI (PyInstaller onedir). Built by `scripts/build_cli.py`.
# The frozen binary also runs the api/worker/migrations through the hidden `_sidecar` subcommand,
# so it needs everything the desktop sidecar bundles plus the CLI and its packaged guide.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

api_root = Path(SPEC).resolve().parent.parent
source_root = api_root / "src"
cli_root = source_root / "bento" / "interfaces" / "cli"
guide = cli_root / "guide.md"
if not guide.is_file():
    raise SystemExit(f"bento-cli.spec: missing packaged agent guide {guide}")

# PyInstaller needs a script; the CLI is a console-script function, so generate a tiny entry point.
entry = Path(workpath) / "bento_cli_entry.py"
entry.parent.mkdir(parents=True, exist_ok=True)
entry.write_text(
    "import multiprocessing\n"
    "import sys\n"
    "\n"
    "from bento.interfaces.cli.main import main\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    multiprocessing.freeze_support()\n"
    "    sys.exit(main())\n",
    encoding="utf-8",
)

datas = [
    (str(api_root / "alembic.ini"), "."),
    (str(api_root / "migrations"), "migrations"),
    (str(guide), "bento/interfaces/cli"),
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
# Bento resolves some modules at runtime (the MTProto runtime, CLI command modules) and watchdog
# picks its observer per platform, so static analysis alone would miss them.
hiddenimports += collect_submodules("bento")
hiddenimports += collect_submodules("watchdog.observers")

# `bento --version` and `User-Agent: bento-cli/<version>` read the installed distribution metadata.
for distribution in ("alembic", "bento-api", "fastapi", "httpx", "pydantic", "segno", "sqlalchemy", "uvicorn"):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

try:
    datas += collect_data_files("rapidocr")
except Exception:
    pass

analysis = Analysis(
    [str(entry)],
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
    name="bento",
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
    name="bento",
)
