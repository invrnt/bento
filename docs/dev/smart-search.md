# Smart search: pins, packaging and bumps

Smart search (búsqueda por significado) embeds documents and queries on the device with a pinned model run by a bundled `llama-server`. This page is the maintainer procedure: what is pinned where, how it is packaged, and how to move to a new model or a new llama.cpp build. The design and the decisions (D1-D9) are in [the smart search program](../../orchestration/execution/smart-search-program.md); the model research is in [embedding-models-2026.md](../../orchestration/research/embedding-models-2026.md).

## What is pinned, and where

| Pin | Source of truth | Checked by |
|---|---|---|
| Model files (repo, commit, file, size, SHA-256, license, dims, prefixes, pooling) | `apps/api/src/bento/infrastructure/models/manifest.json` (schema in [the API contract](../../orchestration/api/smart-search-contract.md)) | the downloader (streamed SHA-256, then atomic rename); `bento-release models plan` |
| Model license text | `apps/api/src/bento/infrastructure/models/licenses/` | `bento-release models stage` (the mirror must carry it) |
| llama.cpp tag, build number, commit, source tarball SHA-256 | the variables at the top of [`scripts/build-llama-server.sh`](../../scripts/build-llama-server.sh), mirrored in [`scripts/build-llama-server.ps1`](../../scripts/build-llama-server.ps1) | both scripts before extracting; `apps/desktop/tests/llama-packaging.test.ts` (the two scripts agree); `verify-artifacts.mjs` (the packaged build matches the pin) |
| Components compiled into llama-server, with licenses | `print_licenses()` in the shell script (`component \| license \| text`) | the SBOM (`generate-sbom.mjs` reads it) and the [third-party notices](../legal/en/third-party-notices.md) |

Today: EmbeddingGemma 2 Q8_0 at `ggml-org/embeddinggemma-2-GGUF@6ea3e3a309d12a4779cfda98b8c19800d2d5da71` (309,855,456 bytes, SHA-256 `2188ac1d…40b09135`) and llama.cpp `b12777` (commit `caea914e9`, source tarball SHA-256 `d7f875b8…19cd8c`).

## llama-server

Bento builds `llama-server` itself (D4) and never downloads executables at runtime.

```sh
scripts/build-llama-server.sh                 # Linux, macOS → dist/llama-server/<platform>-<arch>/
scripts/build-llama-server.sh --print-licenses
pwsh scripts/build-llama-server.ps1           # Windows, from a Developer PowerShell (clang on arm64)
```

- It downloads `https://github.com/ggml-org/llama.cpp/archive/refs/tags/<tag>.tar.gz` into `~/.cache/bento/llama.cpp/` (`%LOCALAPPDATA%\bento\cache\llama.cpp` on Windows; override with `BENTO_LLAMA_CACHE` or `--source-tarball`) and refuses to extract it unless its SHA-256 matches the pin.
- Flags: `GGML_BACKEND_DL=ON`, `GGML_NATIVE=OFF` and `GGML_CPU_ALL_VARIANTS=ON` on Linux and Windows x64, so one binary picks its CPU backend at runtime (no AVX2 requirement). Windows arm64 has no variants upstream. macOS arm64 uses Metal (embedded library) and Accelerate; macOS x64 is a portable `GGML_NATIVE=OFF` build without Metal. OpenMP, OpenSSL, the web UI and `llama-connect` are off: the server runs `--offline` on loopback.
- Output: `llama-server`, its shared libraries and CPU variants (rpath `$ORIGIN` / `@loader_path`), `licenses/`, `bento-llama-server.json` (pin, flags, target) and `SHA256SUMS`. A second run with the same pin and flags is a no-op.
- `BENTO_LLAMA_EXTRA_CMAKE_ARGS` adds flags for experiments; never for releases.

Where it ships:

- **Desktop**: `npm run package` / `make` → `scripts/build-sidecar.mjs` runs the build script and copies the output to `apps/desktop/resources/sidecars/<platform>-<arch>/llama-server/`, which `forge.config.cjs` ships as an `extraResource`. Main passes `BENTO_LLAMA_SERVER_PATH=<resources>/llama-server/llama-server[.exe]` to the sidecars (packaged builds ignore an inherited value). `verify-artifacts.mjs` checks the packaged folder against the pin and its `SHA256SUMS` (signature instead of hashes in signed builds) and `smoke-packaged.mjs` runs `llama-server --version`. `BENTO_SKIP_LLAMA_SERVER=1` packages without it, for local experiments only; `bento-release build --release` refuses it. `BENTO_LLAMA_SERVER_DIR` points at a prebuilt folder with the same layout.
- **CLI**: `bento-release` runs the build script, then `apps/api/packaging/bento-cli.spec` bundles the folder as `llama-server/` inside the PyInstaller bundle (`sys._MEIPASS/llama-server/`). Release builds require it (`BENTO_REQUIRE_LLAMA_SERVER=1`) and smoke `--version`.
- **Docker**: `docker/api.Dockerfile` builds it with the same script on the runtime's Debian base (the official `ghcr.io/ggml-org/llama.cpp:server-<tag>` image is Ubuntu 26.04, whose glibc is newer). `LLAMA_SERVER_STAGE=llama-server-none docker compose build` skips it.

The desktop host also writes `<data_dir>/run/power.json` (`BENTO_POWER_STATE_FILE`) from the existing power hook: `{on_battery, battery_percent, low_battery, updated_at}`. `low_battery` is true on battery below 20 %, or on battery when the charge is unknown (macOS reads `pmset`, Linux sysfs; Windows reports no charge). Indexing pauses while it is true.

### Which llama-server runs

The worker spawns one `llama-server` (none at all when `embedding_server_url` points at an external server). It
takes the first candidate that is an absolute path to an existing executable file, skipping the others:

1. The `llama_server_path` setting (Settings → Advanced, or the `BENTO_LLAMA_SERVER_BINARY` env var), for a user who wants their own build. It is deliberately separate from `BENTO_LLAMA_SERVER_PATH`, which the desktop host sets to the bundled copy.
2. `BENTO_LLAMA_SERVER_PATH`. The desktop host sets it to the packaged copy, `<resources>/llama-server/llama-server[.exe]`; packaged builds ignore an inherited value, development builds pass an explicit one through (point it at `dist/llama-server/<platform>-<arch>/llama-server`). The Docker image sets `/opt/llama-server/llama-server`.
3. The bundled copy: `llama-server/` inside the CLI's PyInstaller bundle (`sys._MEIPASS/llama-server/`).
4. `llama-server` on `PATH`.

If none is found, smart search reports a runtime error instead of indexing.

### Packaging without llama-server (development)

Building llama-server takes a while on the first run. For local experiments only:

```sh
BENTO_SKIP_LLAMA_SERVER=1 npm --prefix apps/desktop run package        # desktop, no llama-server/ resource
BENTO_SKIP_LLAMA_SERVER=1 scripts/release/bento-release build --only cli   # dry run only
```

`build-sidecar.mjs` skips the build and copy, `forge.config.cjs` leaves out the `extraResource`, and
`verify-artifacts.mjs` and `smoke-packaged.mjs` warn instead of failing. Such a package can't run smart search
unless `BENTO_LLAMA_SERVER_PATH`, the setting or `PATH` provides a binary. `bento-release build --release`
refuses the variable, so a release always bundles llama-server.

## The model mirror (D3)

The manifest lists the Hugging Face URL pinned to the commit first and a copy on a Bento GitHub release second. Each model revision has its own release, `models-<name>-<revision[:8]>` (for example `models-embeddinggemma-2-6ea3e3a3`), published with `--latest=false`, so the file is uploaded once per pin, not with every version.

```sh
scripts/release/bento-release models plan                                 # tags the manifest expects; refuses placeholder repos
scripts/release/bento-release models stage --source ~/Downloads/models    # verify size + SHA-256, add LICENSE-<spdx>.txt, SHA256SUMS(.sig)
scripts/release/bento-release models publish                              # draft → inventory check → publish, never latest
```

- `--source` is a folder with the files downloaded from the manifest's pinned Hugging Face URLs. The tool never downloads; a file whose size or SHA-256 differs from the manifest is not staged.
- Staging signs `SHA256SUMS` with the release key (`--signing-key` or `BENTO_RELEASE_SIGNING_KEY`); publishing verifies it against `scripts/release/allowed_signers`.
- `publish` creates the tag at `HEAD` (`--target`), so push the commit that pins the manifest first. An existing mirror release is never replaced: a new pin gets a new tag.
- After publishing, download the asset from the mirror URL and check that `sha256sum` prints the manifest value: both URLs must yield the same hash.

## Bumping the model

1. Pick the new file in the research doc's terms (license, official GGUF, size, quality) and record the decision in the program doc.
2. Pin it: the repo **commit** (not a branch), the file name, the size and the SHA-256 that Hugging Face shows for the LFS object. Download the file once and check `sha256sum` matches.
3. Copy the license text (and NOTICE, if any) at that commit into `infrastructure/models/licenses/`. Check the card for use-policy lines (D2).
4. Update `manifest.json` and its canonical test copy, including the mirror URL `https://github.com/invrnt/bento/releases/download/models-<name>-<revision[:8]>/<file>` (`bento-release models plan` must report no problem). A new revision is a new embedding space: the app re-indexes blue/green and never auto-downloads; Settings offers the update.
5. Run the opt-in real-model tests (`pytest -m real_model`) and record latency and recall in the research doc. Set the new model's `min_similarity` per dims and `similarity_margin` from `test_real_model_calibration.py` (`BENTO_REAL_MODEL_CALIBRATION_REPORT=<file>` writes the sweep): the highest floor that keeps every relevant document, then the smallest margin that does too. Check the ranking with `test_real_model_hybrid_ranking.py`. Without values the model runs on the 0.30 fallback.
6. Stage and publish the mirror (above), then update the [third-party notices](../legal/en/third-party-notices.md) in both languages and, if the host, size or license changes, the privacy page and the user guides.

## Bumping llama.cpp

1. Read the release notes between the current tag and the new one for changes to `llama-server` flags, `/v1/embeddings`, `/tokenize`, pooling or the `gemma-embedding2` architecture. Update the fake server (`tests/fakes/llama_server.py`) if the API changed.
2. Download `https://github.com/ggml-org/llama.cpp/archive/refs/tags/<tag>.tar.gz`, compute its SHA-256, and note the commit (`llama-server --version` of the official release prints it).
3. Update `LLAMA_CPP_TAG`, `LLAMA_CPP_BUILD_NUMBER`, `LLAMA_CPP_COMMIT` and `LLAMA_CPP_SOURCE_SHA256` in **both** build scripts. Check the CMake options still exist (`grep -n "option(" CMakeLists.txt ggml/CMakeLists.txt`): options are renamed from time to time, and a new default-on download (prebuilt UI, BoringSSL, OpenMP fetch) must be switched off.
4. Re-check the vendored components (`vendor/`, `licenses/`) and update `print_licenses()` in both scripts and the third-party notices.
5. Build on each platform, run the opt-in real-model test, then `npm --prefix apps/desktop run make`, `verify:artifacts` and `smoke:packaged`.

Never change a pin in the same commit as unrelated work, and never point a URL at a branch.
