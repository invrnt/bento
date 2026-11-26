# Standalone `bento` CLI (PyInstaller onedir). Built by `scripts/build_cli.py`.
# The frozen binary also runs the api/worker/migrations through the hidden `_sidecar` subcommand,
# so it needs everything the desktop sidecar bundles plus the CLI and its packaged guide.
import importlib.util
import os
import platform
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

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

# llama-server for smart search in `bento daemon` (D4): the output of scripts/build-llama-server.{sh,ps1}
# for this machine, bundled as `llama-server/` (the backend resolves `sys._MEIPASS/llama-server/`). Release
# builds set BENTO_REQUIRE_LLAMA_SERVER=1; otherwise a missing build only disables smart search.
_system = {"win32": "win32", "darwin": "darwin"}.get(sys.platform, "linux")
_machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
llama_dir = Path(os.environ.get("BENTO_LLAMA_SERVER_DIR") or api_root.parent.parent / "dist" / "llama-server" / f"{_system}-{_machine}")
llama_executable = llama_dir / ("llama-server.exe" if sys.platform == "win32" else "llama-server")
if llama_executable.is_file():
    for item in sorted(llama_dir.rglob("*")):
        if not item.is_file():
            continue
        destination = str(Path("llama-server") / item.parent.relative_to(llama_dir))
        if item == llama_executable or item.suffix.lower() in {".so", ".dylib", ".dll"}:
            binaries.append((str(item), destination))
        else:
            datas.append((str(item), destination))
elif os.environ.get("BENTO_REQUIRE_LLAMA_SERVER") == "1":
    raise SystemExit(f"bento-cli.spec: llama-server not found at {llama_dir}; run scripts/build-llama-server.sh first")
else:
    print(f"bento-cli.spec: warning: no llama-server at {llama_dir}; the bundle will not offer smart search")

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
