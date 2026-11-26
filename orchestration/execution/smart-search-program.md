# Smart Search Program (Stages 23-26)

Goal: one-click, fully on-device smart search (búsqueda por significado). The person turns on one switch in Ajustes › Búsqueda inteligente; Bento shows the size and license, downloads a pinned model in the background with progress, pause/resume and resume after a dropped connection, verifies a pinned SHA-256, starts a local llama.cpp embedding server, indexes the library with the CPU-safe defaults and reports clear states. Nothing about the person's files leaves the device and there is no telemetry.

Binding research: `research/embedding-models-2026.md` (model choice, licenses, file pins, llama.cpp distribution). It replaces the earlier `jina-embeddings-v5-omni-nano` target: that model is CC BY-NC 4.0 and has no official GGUF.

## Model pins (from the research, 2026-11-26)

| Role | Repo @ commit | File | Bytes | SHA-256 | License | Dims | Prefixes |
|---|---|---|---|---|---|---|---|
| **Default text** | `ggml-org/embeddinggemma-2-GGUF` @`6ea3e3a309d12a4779cfda98b8c19800d2d5da71` (source `google/embeddinggemma-2` @`f9972ac2`) | `embeddinggemma-2-Q8_0.gguf` | 309,855,456 | `2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135` | Apache-2.0 | 768 (MRL 512/256/128) | query `task: search result \| query: {q}` · doc `title: {title\|none} \| text: {chunk}` · mean pooling |
| Image add-on (Stage 26) | same repo/commit | `mmproj-embeddinggemma-2-Q8_0.gguf` | 554,821,056 | `0531309472a6bc6f4b146c3736eee7795ec9db1903c25490d3c937490cef6dd8` | Apache-2.0 | same space | images: no prefix |
| Fallback text | `Qwen/Qwen3-Embedding-0.6B-GGUF` @`370f27d7550e0def9b39c1f16d3fbaa13aa67728` | `Qwen3-Embedding-0.6B-Q8_0.gguf` | 639,150,592 | `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439` | Apache-2.0 | 1024 (MRL 32-1024) | query `Instruct: Given a search query, retrieve relevant files\nQuery:{q}` · doc none · last pooling |
| Runtime | `ggml-org/llama.cpp` tag `b12777` (minimum `b11454`, which adds the `gemma-embedding2` architecture) | `llama-server` built by Bento | — | per-build, in `SHA256SUMS` | MIT | — | — |

`-c 2048 -ub 2048 -b 2048 -np 1 --pooling mean` for the default. `-c` must be set explicitly because the GGUF advertises 262,144 tokens. Never use F16 weights for EmbeddingGemma 2: its card warns that F16 produces NaN. The SHA-256 values are the HF LFS object ids and must be re-checked when the manifest is written.

Scope: web UI + desktop (Electron) + headless/CLI daemon + Docker. Android: decision in §Android below (query-only smart search behind a Stage 26 gate; full on-phone indexing is out of scope).

## Why the current code needs more than a model swap

Findings from the code as of `6be1944a` (2026-11-26):

1. Nothing starts a llama.cpp server. `JinaOmniNanoGgufAdapter` (`adapters/embeddings/jina.py`) posts to `embedding_server_url` (`http://127.0.0.1:8080/v1/embeddings`) and only checks that `jina_model_path` exists. The person would have to install llama.cpp, start it by hand on that port, and type a GGUF path. The web copy (`smartSearch.semantic.body`) already promises "the first time it downloads a model in the background", which the code does not do.
2. Its image request body (`input: {type, image_url}`) is not the shape llama-server accepts for multimodal embeddings (`input: [{content: [{type: "image_url", …}]}]`, `--mmproj` required). Image embeddings never worked against a real server.
3. There is no query/document asymmetry: search embeds the query with the same `embed_text` call as documents. Every candidate model needs a task prefix (`task: search result | query: `, `Instruct: …\nQuery:`, `query: `/`passage: `), so recall would be poor even with a model.
4. One vector per asset over the whole concatenated text, with no chunking and no length cap. Long PDFs blow past the model context (llama-server rejects inputs above `n_ubatch` for non-causal models).
5. The vector index is not tagged with an embedding space. `asset_embedding_vec` is `vec0(embedding float[N])` with `N` fixed at creation; `asset_embeddings.provider` exists but search does not filter by it, and synced peer vectors (`adapters/sync/index_data.py`) are accepted whenever the dimensions match, so two devices on different models would silently mix spaces.
6. `sqlite-vec` is not a dependency of any profile (`pyproject.toml`), so every install runs the brute-force `asset_embedding_vectors_fallback` path in Python. That is fine below ~50 k vectors at 256-768 dims, but it should be a deliberate choice.
7. The desktop sidecar already bundles `onnxruntime` and RapidOCR (`desktop` extra, `packaging/bento-sidecar.spec`); it bundles no native binaries of its own (`binaries = []`), and ffmpeg comes from the system `PATH`.

## Product contract (binding for Stage 25 UI)

Settings › Smart search › "Search by meaning" becomes a managed capability. The switch stays as it is today (`SmartSearchSection.tsx`), and turning it on opens a confirmation sheet instead of saving `embeddings_provider` right away.

Spanish copy (source of truth; English is translated by dictionary):

| Key | es |
|---|---|
| `smartSearch.semantic.label` | Buscar por significado |
| `smartSearch.semantic.body` | Encuentra cosas aunque no recuerdes las palabras exactas, como «cumpleaños en la playa». Funciona en este equipo, sin internet. |
| `smartSearch.activate.title` | Activar la búsqueda por significado |
| `smartSearch.activate.body` | Bento descargará un modelo de {size} desde {host} y lo guardará en este equipo. Después revisará tus archivos poco a poco, sin frenar el equipo. Tus archivos no salen de este equipo. |
| `smartSearch.activate.license` | Modelo: {modelName} · Licencia {license} |
| `smartSearch.activate.confirm` | Descargar y activar |
| `smartSearch.activate.space` | Necesitas {size} libres. Ahora tienes {free}. |
| `smartSearch.state.downloading` | Descargando… {done} de {total} |
| `smartSearch.state.paused` | En pausa · {done} de {total} |
| `smartSearch.state.waitingNetwork` | Esperando conexión · se reanudará sola |
| `smartSearch.state.verifying` | Comprobando el archivo… |
| `smartSearch.state.starting` | Preparando… |
| `smartSearch.state.indexing` | Revisando tus archivos · {done} de {total} |
| `smartSearch.state.ready` | Lista |
| `smartSearch.state.error.download` | No se pudo descargar el modelo. |
| `smartSearch.state.error.checksum` | El archivo descargado no es correcto y se borró. |
| `smartSearch.state.error.space` | No hay espacio suficiente en este equipo. |
| `smartSearch.state.error.runtime` | El motor de búsqueda no pudo iniciar en este equipo. |
| `smartSearch.action.pause` / `resume` / `retry` / `cancel` | Pausar / Reanudar / Reintentar / Cancelar |
| `smartSearch.action.remove` | Quitar el modelo y liberar {size} |
| `smartSearch.remove.confirm` | La búsqueda por nombre, fecha y texto seguirá funcionando. Puedes volver a activarla cuando quieras. |

States (one domain enum, `SmartSearchState`): `off → downloading ⇄ paused → verifying → starting → indexing → ready`; any of `downloading/verifying/starting/indexing` → `error(code)` → `retry` returns to the step that failed (download resumes from the partial file; a checksum error restarts from zero). `waiting_network` is a sub-state of `downloading`. `ready` with new files shows `indexing` again only when the backlog is over 50 items (no flicker for one upload).

Accessibility: the switch, sheet and progress are keyboard reachable in order; progress is a `role="progressbar"` with `aria-valuenow/max` and a text equivalent; state changes are announced through the existing polite live region, at most every 10 % or on state change; the remove action is a destructive confirm dialog with focus returned to the trigger; visible focus everywhere (`i18n-a11y.md`).

Privacy: the download is the only network call. It sends no identifiers beyond what HTTPS needs (no cookies, no `Authorization`, a generic `User-Agent: Bento/<version>`). Everything else stays local. The privacy page names the download host (see §Legal).

## Distribution decisions (proposed; owner confirms in §Decisions)

- **Model file**: download from the publisher's Hugging Face repo, **pinned to a commit**: `https://huggingface.co/<repo>/resolve/<commit-sha>/<file>`, and verify against the SHA-256 that Hugging Face publishes for that LFS object (recorded in the manifest at pin time). Mirroring the file as a Bento GitHub release asset is allowed by Apache-2.0 if the LICENSE text goes along. The source repos ship no LICENSE file, so Bento ships the Apache-2.0 text from `infrastructure/models/licenses/` and is kept as the **fallback URL** in the manifest, uploaded by `bento-release`. Reasons for HF first: no 300 MB+ per-release upload, no bandwidth bill, and the pin plus hash gives the same integrity. Reasons to keep the mirror: HF outages, rate limits, or the publisher deleting the repo. The downloader tries the URLs in order; both must yield the same hash.
- **llama.cpp server**: Bento builds `llama-server` itself from tag `b12777` (`scripts/build-llama-server.{sh,ps1}`, run by `bento-release` on each platform) for linux-x64, linux-arm64, win32-x64, win32-arm64, darwin-arm64 and darwin-x64.
  - Build flags: `-DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON` on x64 and arm64 Linux/Windows, plus `-DLLAMA_CURL=OFF` and no examples or tests. macOS arm64 uses Metal/Accelerate. macOS x64 uses `GGML_NATIVE=OFF`: the official macOS x64 release sets neither flag and may need the CI runner's CPU features.
  - Why not repackage the official archives: they are not codesigned or notarized for macOS, they carry no Authenticode signature, Windows Defender has false-flagged them (#15874), and the Android archive alone is 82.9 MB.
  - Fallback if the build is blocked: take the official `llama-b12777-bin-*` archives, check them against the GitHub asset digest and `gh attestation verify`, then re-sign them ourselves.
  - Every binary and `ggml-cpu-*.so/.dll/.dylib` gets the desktop app's signing (Authenticode; codesign with hardened runtime and notarization).
  - It ships **inside the desktop installer** as an `extraResource` next to `bento-sidecar`. Bento never downloads executables at runtime. The cost is about 12-25 MB per installer: the official CPU archives are 12.6-25.2 MB compressed at b12777 and include tools Bento doesn't ship. Docker gets the binary from the pinned `ghcr.io/ggml-org/llama.cpp:server-<tag>` stage in a multi-stage build, or from the same build script. The CLI's PyInstaller bundle includes it the same way. A user-supplied `llama_server_path` (Advanced) overrides it.
- **Integrity**: a **model manifest** ships inside the Python package (`bento/infrastructure/models/manifest.json`, version-controlled, reviewed like code). It lists each file's URL list, size and SHA-256, plus the license SPDX id, the dims, the prefixes and the pooling. The file is streamed to `<data_dir>/models/<model_id>/<revision>/<file>.part` while the SHA-256 is computed, then fsynced and atomically renamed only when the hash matches. A mismatch deletes the part file. The worker re-verifies the size and an mtime marker on each start; it re-hashes fully only when they change. The `llama-server` binary is covered by the installer's signature and by `SHA256SUMS`.
- **Model updates**: a new model or revision is a Bento release that changes the manifest. The app never auto-downloads a new model. When the installed revision is no longer in the manifest, Settings shows "Hay una versión nueva del modelo ({size})" with an update action. Search keeps using the installed model until the new one is downloaded, verified and has re-indexed (blue/green spaces, §Re-indexing). The old files are deleted only after that switch.

## Architecture

Dependency rules from `AGENTS.md` hold: the domain is pure, the application talks only to ports, and the adapters implement those ports.

```
domain/smart_search.py        EmbeddingSpace, ModelSpec, ModelFile, SmartSearchState/Status, transitions, chunking rules
ports/models.py               ModelCatalogPort, ModelDownloaderPort, ModelStorePort, EmbeddingRuntimePort
ports/providers.py            EmbeddingProviderPort → embed_query / embed_documents / embed_image (+ space)
application/smart_search/     activation.py (activate/pause/resume/retry/cancel/remove/status, update),
                              runtime.py (ensure server for the active space), reembed.py (space migration)
application/indexing/         embedding.py: chunks + document prefix + batches; reindex.py: space-aware
adapters/models/              http_downloader.py (urllib, Range resume, rate-limited progress),
                              filesystem_store.py (data_dir/models layout, .part, atomic rename, free space),
                              manifest_catalog.py (reads packaged manifest.json)
adapters/embeddings/          llama_cpp.py (generic OpenAI-shape client: prefixes, batching, Matryoshka
                              truncate + renormalise, multimodal content parts) — replaces jina.py
adapters/runtime/             llama_server_process.py (spawn/health/stop, Unix socket or 127.0.0.1 + random
                              port, --api-key-file, --no-webui, --offline, threads = min(4, cores//2))
adapters/search/sqlite_vec.py per-space tables, space filter on search and on synced vectors
interfaces/http/routes_smart_search.py   GET status, POST activate|pause|resume|retry|cancel|update, DELETE model
interfaces/worker/            model_download + reembed job handlers; runtime owner
infrastructure/models/        manifest.json, paths, binary resolution (packaged → setting override → PATH)
```

- **Who runs llama-server**: the **worker** owns it. The worker is always running on desktop, the CLI daemon and Docker, and it does the bulk embedding. It writes `<data_dir>/run/embedder.json` (mode 0600) with `{socket|port, api_key_file, space_id, pid, started_at}`. The API reads that file to embed queries and treats "missing or unhealthy" as "vector search unavailable", so search falls back to FTS and keeps working, as it does today. A second server process would double the RAM. The worker restarts the server on crash with backoff (1 s → 60 s, 5 tries, then `error(runtime)`). It stops the server when smart search is turned off or the model is removed.
- **Server hardening**: bind to a Unix socket on Linux and macOS, and on Windows to `127.0.0.1` on a random free port. The per-launch API key goes in a 0600 file. Use `--no-webui`, `--offline` and `--embeddings`, with `--pooling` from the manifest and `-c`/`-ub` from the manifest (for example 2048/2048). Use `-np 1` and `child_environment()` (allowlisted env). Never log the request bodies.
- **Ports** (sketch):
  - `ModelCatalogPort.default() -> ModelSpec`, `.get(model_id, revision)`.
  - `ModelDownloaderPort.download(file: ModelFile, dest_part: Path, on_progress, should_stop) -> DownloadOutcome`. It resumes from `dest_part.stat().st_size` with `Range`, checks for `206` and `Content-Range`, and restarts from zero on `200` or when the ETag changes. It calls `check_safe_boundary()` between 4 MiB blocks, so Android budgets and pause work.
  - `ModelStorePort.installed() / path_for(spec) / free_bytes() / remove(spec) / verify(spec)`.
  - `EmbeddingRuntimePort.ensure(spec, paths) -> EndpointInfo`, `.stop()`, `.health()`.
  - `EmbeddingProviderPort.space -> EmbeddingSpace`, `embed_query(text)`, `embed_documents(texts)`, `embed_image(path)` (raises `Unsupported` for text-only spaces).
- **Embedding space**: `EmbeddingSpace(id="<model_id>@<revision>/<dims>", dims, modalities)`. Every stored vector carries its `space_id`. Search only queries the active space. Synced `asset_index.embedding` gains `space` and is indexed only when it equals the local active space. Otherwise it is stored and indexed later, if the person switches to that space. Old peers that send only `provider` are treated as an unknown space.
- **Chunking**: documents become ≤ 512-token windows. Token counts are estimated with a character budget per language (about 4 characters per token) and checked against the server's `/tokenize` in tests. Windows are capped at 16 chunks per asset, the first pages first. Vectors go into `asset_embedding_chunks(space_id, asset_id, chunk_no, vector)`. An asset's search score is the best of its chunks. Images: OCR text plus filename/EXIF/album metadata as text in v1. Image pixels are embedded only when the active space is multimodal (§Images).
- **Batching and CPU-safe defaults**: one embedding job per asset as today (`JobPriority.EMBEDDING` after thumbnails and OCR). Within a job, chunks are sent in batches of 8, with `worker_concurrency` 1. A new `embedding_threads` setting (default `min(4, max(1, cores // 2))`) goes to `-t`. Indexing pauses while on battery below 20 % (existing `DeviceConditions` on Android; desktop `powerMonitor` through the existing power hook). Thumbnails and OCR always run before embeddings.
- **Settings changes** (`domain/settings_registry.py`, `application/settings.py`):
  - `embeddings_provider` choices become `disabled | managed | custom | mock`. `jina` is migrated to `custom` if `jina_model_path` points to an existing file, otherwise to `disabled`.
  - `smart_search_model` (choice from the manifest, default the recommended model; hidden unless there is more than one).
  - Advanced (group `ai`, `advanced=True`): `custom_model_path` (renamed from `jina_model_path`; old env aliases `JINA_MODEL_PATH` and `BENTO_EMBEDDING_MODEL_PATH` kept), `custom_mmproj_path`, `custom_query_prefix`, `custom_document_prefix`, `custom_pooling`, `embedding_dimensions` (validated against the spec's Matryoshka list in `managed` mode), `llama_server_path`, `embedding_server_url` (external server; when set, Bento does not spawn one), and `embedding_threads`.
  - Runtime state (not settings): `smart_search_status` row (state, bytes, error code, space) in SQLite, exposed in `GET /api/smart-search` and folded into the existing `embeddings_state`/`model_available` fields for old clients.
- **Re-indexing when the model or dimensions change**: activating a new space creates its tables, then queues `reembed` (paged like `ReindexService`) for this device's own assets (`ai_indexing_allowed`). Until the new space reaches 100 %, or the person chooses "use it now", search keeps the old space. Then the active pointer flips atomically, the old space's rows are dropped, and its files are deleted. A dimension change through the Advanced setting is a new space too. Telegram-origin and peer assets are still never embedded locally.
- **Migrations** (one Alembic revision, `0009_smart_search`):
  - Add `space_id` to `asset_embeddings` (backfill `legacy:<provider>/<dims>`) and add the `asset_embedding_chunks` table.
  - Add `embedding_spaces(id, model_id, revision, dims, modalities, state, created_at, activated_at)` and `model_installs(model_id, revision, file, bytes_total, bytes_done, sha256, state, error_code, updated_at)`.
  - Rewrite the settings rows: `jina` → `custom`/`disabled`, `jina_model_path` → `custom_model_path`.
  - Legacy vectors stay readable under their legacy space. They are not deleted until the person activates a managed space.
  - `vec0` virtual tables are created at runtime per space (`asset_embedding_vec_<hash8>`), because their dimension is part of the DDL. The migration does not create them.
- **sqlite-vec**: add `sqlite-vec` (Apache-2.0/MIT dual) to the `desktop` extra and bundle its loadable extension through the PyInstaller spec (`collect_dynamic_libs("sqlite_vec")`). Keep the fallback for Docker dev, Android, and when the extension fails to load. Open decision D7.

## Images (search photos by description)

Bento needs a permissive way to search images by meaning. It has two steps:

- **v1 (Stage 24, always on)**: images go through OCR text plus filename, album, folder, date and place, embedded as text in the default space. That adds no extra size. It covers screenshots, documents and receipts. It does not cover "perro en la playa" for a photo with no text.
- **v2 (Stage 26, opt-in "Buscar fotos por lo que muestran", a separate +555 MB download)**: the EmbeddingGemma 2 `mmproj` is loaded into the same llama-server (`--mmproj`). Photos are embedded from their **preview** (≤ 768 px, never the original) into the **same vector space** as the text, so documents don't need re-embedding and one text query finds both. It is a second managed file with its own size, license line, progress and remove action. Its CPU cost is about 0.3-1 s per photo (est.), so it runs only while the computer is plugged in and idle, newest photos first.
  - Spike gate: llama.cpp issue #30195 reported 3.6k-13k tokens per image instead of about 280. Measure the tokens and time per image at the pinned tag first.
  - If the spike fails, the alternative is SigLIP2-base-patch16-224 on the onnxruntime already in the desktop bundle. It is Apache-2.0, adds about 378 MB int8, uses a separate image space, and scored 83.6 % on Immich's Spanish benchmark. Captioning with a small VLM is not recommended: it is 4-10 s per photo (est.), it hallucinates, and "no automatic captions" is a non-goal.

## Android decision

v1 Android keeps search by meaning **off**, the same as `android-runtime.md` §Defaults. Feasible later as **query-only smart search** (Stage 26 gate):

- The phone does not embed the library. Desktops already publish embeddings through `asset_index` ops, and Android already stores them ("stored, not indexed").
- The phone embeds only the query: one short text, about 50-150 ms on a mid-range arm64 CPU with EmbeddingGemma 2 Q8_0 (est., to confirm in the spike). Chaquopy has no llama-cpp-python or onnxruntime wheel, so inference has to run on the Kotlin side. It uses llama.cpp built with the NDK (`-DANDROID_ABI=arm64-v8a -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON -DGGML_OPENMP=OFF`) as a JNI library (`libbento_llama.so`), behind a new `EmbeddingBridge` in `core/engine`. The alternative is LiteRT with `litert-community/embeddinggemma-2-740m-litert-lm` (484.6 MB). Chaquopy calls it through the bridge pattern of `android-runtime.md` §5. There is no `exec` of a server binary.
- The same managed download, verification and UI states are used, with Wi-Fi only by default, and indexing of the peer vectors happens in the Python fallback index.
- Cost: about 2-4 MB per ABI for the `.so` (estimate), plus a model download of the default's size. The model is memory-mapped, and the mapped size counts toward PSS under memory pressure only when its pages are touched. Budget: the engine's 160 MB plus about the model's resident size. Gate on 6 GB RAM devices and up; below that the option is hidden.
- Go/no-go criteria for the spike: the query embedding has identical cosine to desktop's (≥ 0.999) for 100 fixed queries, p90 query latency ≤ 300 ms on the floor device, no OOM kill during a search session on a 4 GB device with the option hidden, and the APK grows ≤ 5 MB.

## Legal

Changes go in the same commit as the feature (Stage 25 docs agent). Rule from `docs/legal/README.md`: the site pages are the source of truth.

- `docs/legal/en/third-party-notices.md` and `docs/legal/es/avisos-de-terceros.md`, §Smart search:
  - Replace the "Bento does not include or download the model … Jina … CC BY-NC 4.0" paragraph with the managed model's name, publisher, license, source URL pinned to a commit, and file hash.
  - Say that Bento downloads it only when the person turns the feature on.
  - Add `llama.cpp` (MIT, ggml-org) with its bundled components. The build script prints the list, for example `cpp-httplib` (MIT), `nlohmann/json` (MIT), `miniaudio`/`stb` (public domain/MIT) if compiled in.
  - Add `sqlite-vec` (Apache-2.0 OR MIT) if D7 is accepted.
  - Ship the model's LICENSE (and NOTICE, if any) next to the downloaded file, and show it from Settings › Smart search ("Ver licencia").
  - If a Gemma-licensed model is chosen, see D2.
- `apps/site/src/privacy/index.html` and `apps/site/src/en/privacy/index.html`, row "Modelo de búsqueda inteligente (opcional)":
  - Rewrite it to say: "Solo si activas la búsqueda por significado. Bento descarga el modelo desde Hugging Face (huggingface.co) o, si no está disponible, desde GitHub (github.com). Ese servicio recibe tu dirección IP y la versión pedida según su propia política. No se envía ningún dato de tus archivos."
  - Remove "Bento no descarga modelos automáticamente sin tu acción; si obtienes el archivo…" and replace it with the new wording.
- `apps/site/src/terms/index.html` and `apps/site/src/en/terms/index.html`, §9 Servicios de terceros:
  - Add that the smart search model is third-party software under its own license, linked from the notices.
  - Add that its results are probabilistic and can miss files.
- `apps/site/src/security/*`: one line saying the model file is pinned and SHA-256 verified, and that the embedding server listens only locally, on a Unix socket or loopback with a per-launch key.
- User guides: `docs/user/{es,en}/{primeros-pasos,getting-started,privacidad-y-seguridad}.md` replace "you provide the model" wording.

## Stages

### Stage 23 — Contracts and research gate (sequential, small)

| Agent | Owns |
|---|---|
| smart-search-contracts | `domain/smart_search.py`, `ports/models.py`, `ports/providers.py` (additive methods), `api/smart-search-contract.md` (new, orchestration), `product/search.md` + `product/indexing-media.md` (smart search sections), `architecture/system-overview.md` (adapter list line), tests `tests/unit/smart_search/**` |

The domain is the state machine, `ModelSpec`/`EmbeddingSpace`, the chunker and the Matryoshka truncate+renormalise, all as pure functions. The owner reviews the research doc and answers §Decisions D1-D4 before Stage 24 starts.

Exit: state-transition property tests (every illegal transition raises), chunker golden tests (es/en texts, CJK, emoji, 0-length), and truncate+renormalise unit tests. The `/api/smart-search` contract is reviewed.

### Stage 24 — Backend engine (parallel)

| Agent | Owns |
|---|---|
| models-download | `adapters/models/**`, `infrastructure/models/**` (manifest.json + loader), `application/smart_search/activation.py`, the `model_download` job type in `domain/jobs.py` (one enum line) + its handler in `interfaces/worker/handlers_models.py`, `interfaces/http/routes_smart_search.py` (+ one `include_router` line), tests `tests/unit/models/**`, `tests/api/smart_search/**` |
| embeddings-runtime | `adapters/embeddings/llama_cpp.py` (+ delete `jina.py` and update `adapters/embeddings/__init__.py`), `adapters/runtime/**`, `application/smart_search/runtime.py`, `application/indexing/embedding.py`, `interfaces/worker/main.py` (provider/runtime wiring), `scripts/benchmark/embedding_timing.py`, tests `tests/unit/embeddings/**`, `tests/integration/embeddings/**` |
| vector-index-migration | `adapters/search/sqlite_vec.py`, `adapters/search/composite.py` (vector part + query embedding call only), `adapters/sync/index_data.py` + `application/sync/asset_index.py` (space field), `application/indexing/reindex.py`, `application/smart_search/reembed.py`, `infrastructure/db/models.py` + migration `0009_smart_search`, settings registry/validation (`domain/settings_registry.py`, `application/settings.py`, `infrastructure/settings.py`, `adapters/settings/**`), `interfaces/desktop/launcher.py` (`model-file` probe → `custom_model_path`), tests `tests/unit/search/**`, `tests/integration/search/**`, `tests/integration/migrations/**` |

Contracts between them: the ports from Stage 23, `api/smart-search-contract.md`, and `run/embedder.json` (owned by embeddings-runtime, read by vector-index-migration through `EmbeddingRuntimePort.endpoint()`).

Tests (no real AI providers, no network, no large files):
- **FakeHttpServer** (`tests/fakes/model_host.py`): serves a 3 MB synthetic blob with `Range`/`206`/ETag. It injects drops at a byte offset, returns 200 when 206 was asked, 404 on the primary URL, a slow trickle, and a wrong body for the checksum test.
- The download tests cover resume after a kill, pause/resume, falling back to the mirror URL, a checksum mismatch deleting the part file, the free-space precheck, a cancel that leaves no residue, and remove freeing the bytes.
- **FakeEmbeddingServer** (`tests/fakes/llama_server.py`): an aiohttp-free `http.server` speaking llama-server's `/health`, `/v1/embeddings` (string, string-array and content-part inputs) and `/tokenize`. It returns deterministic vectors from a hash of the prefix plus the text, and it checks the API key.
- **FakeLlamaServerBinary**: a tiny Python script launched through the same process adapter. It tests argv (flags, socket, key file), readiness polling, crash/restart backoff, and stop on disable.
- Asymmetric prefixes are asserted on the wire. Chunk batching is asserted (batches of 8, ≤ n_ubatch).
- Space isolation: vectors from space A are never returned for space B, peer vectors from another space are not indexed, and the blue/green flip happens at 100 %.
- Migration tests run from 0008 with legacy jina rows and settings.
- sqlite-vec and the fallback return the same top-k.
- One **opt-in** local test (`-m real_model`, skipped by default and in local CI) runs the real pinned GGUF and a real llama-server to record latency and recall on a 200-doc es/en fixture.

Exit: the backend suite is green. `scripts/local-ci.sh` is green. An end-to-end API journey with the fake host and fake server goes activate → downloading → paused → resumed → verifying → starting → indexing 20/20 → ready → search returns a vector hit → remove → disabled, with the disk usage back to the baseline.

### Stage 25 — Product surfaces, packaging, legal (parallel)

| Agent | Owns |
|---|---|
| web-smart-search | `apps/web/src/features/settings/SmartSearchSection.tsx` (+ new `smart-search/` subfolder: sheet, progress, query hooks `useSmartSearchStatus`/mutations), `apps/web/src/api/smartSearch.ts`, i18n keys `smartSearch.*` in `apps/web/src/i18n/{es,en}/onboarding.ts`, `AdvancedSection.tsx` (model path field → custom model group), `JobsPage.tsx` (model_download/reembed labels), tests `apps/web/src/test/settings/smart-search*.test.tsx` |
| desktop-llama-packaging | `scripts/build-llama-server.{sh,ps1}`, `apps/desktop/forge.config.cjs` (`extraResource` llama-server), `apps/desktop/scripts/{build-sidecar,verify-artifacts,generate-sbom,checksums}.mjs` (llama-server entries), `apps/desktop/src/main/sidecars.ts` (pass `BENTO_LLAMA_SERVER_PATH` + power state to worker), `apps/api/packaging/bento-sidecar.spec` + `bento-cli.spec` (sqlite-vec extension; llama-server for CLI bundle), `docker/**` + `docker-compose.yml` (llama-server stage), release tool hooks for the optional model mirror asset, tests `apps/desktop/tests/llama-packaging.test.ts` |
| smart-search-docs-legal | `docs/legal/{en,es}/*third-party*`, `apps/site/src/{privacy,terms,security}/index.html` + `apps/site/src/en/{privacy,terms,security}/index.html`, `docs/user/{es,en}/**` (smart search mentions), `docs/dev/smart-search.md` (pinning procedure, how to bump the model), `orchestration/README.md` status line, `CHANGELOG.md` entry |

Tests:
- **Web**: component tests for every state with MSW-style fetch fakes. They cover the confirmation sheet showing the size, license and host, keyboard-only activation and pause/resume, the progressbar's aria values, live-region announcements throttled, the remove dialog's focus return, the error + retry for each error code, and the locked state when env-controlled. No real provider is used.
- **Desktop**: the packaged app contains `llama-server` for its platform/arch, it is signed, verify-artifacts checks its hash, and the smoke test (`smoke-packaged.mjs`) runs `llama-server --version`.
- **Site**: the existing site tests, plus "no `[[COMPLETAR` placeholders" and the new privacy row present in es/en.

Exit: the web, desktop and site suites are green. A manual pass on Linux, plus whatever macOS/Windows machines are available, with the real pinned model: turn on → download (pull the network cable mid-way, it resumes) → ready → search «facturas de luz» and «fotos de la playa» → remove. Record the timings in `execution/evidence/`.

### Stage 26 — Optional tracks (each behind its own gate)

| Track | Owns | Gate |
|---|---|---|
| image-meaning (desktop) | mmproj manifest entry, `--mmproj` launch option and `embed_image` with preview input in `adapters/embeddings/**` + `adapters/runtime/**`, an image `reembed` pass, the UI sub-switch, tests (the fake server gains content-part image inputs) | D5. The spike measures llama.cpp #30195's tokens per image and the seconds per photo at the pinned tag; quality check: ≥ 0.6 recall@10 on a 200-photo es/en labelled fixture kept outside the repo |
| android-query-only | `apps/android/core/engine` (`EmbeddingBridge`, NDK build of llama.cpp), `adapters/android/embeddings_bridge.py`, `feature/settings` smart search screen, strings | Spike go/no-go in §Android; owner decision D6 |

## Parallel workstream ownership summary

- Stage 23: smart-search-contracts owns `domain/smart_search.py`, `ports/models.py` and `ports/providers.py`. Nobody else touches them in Stages 23-25 (later additions go through a handoff request).
- Stage 24: three backend agents with disjoint paths, as listed above. `interfaces/worker/main.py` belongs to embeddings-runtime only. models-download registers its job handler through `interfaces/worker/dispatch.py` and asks embeddings-runtime for the one-line wiring in its handoff. `domain/jobs.py` gets one enum line from models-download and one from vector-index-migration (`REEMBED`). The orchestrator merges them in the order models-download → embeddings-runtime → vector-index-migration.
- Stage 25: web, desktop/packaging and docs/legal are disjoint by directory. `orchestration/README.md` belongs to docs-legal only.

## Risks

| Risk | Mitigation |
|---|---|
| A pinned HF commit is deleted or gated, or HF throttles downloads | Mirror on Bento's GitHub release (license permitting); manifest URL list; same hash for both |
| llama.cpp flags or API change between tags | Pin the tag; the fake server mirrors the pinned README; the opt-in real test before each bump |
| Old CPUs without AVX2 (or Windows ARM) | `GGML_CPU_ALL_VARIANTS` + backend-DL builds; `error(runtime)` with a clear message; the FTS search still works |
| Antivirus/Gatekeeper flags `llama-server` | Ship it signed inside the installer; never download executables |
| RAM spikes on 8 GB machines during indexing | `-np 1`, `-c` ≤ 2048, batch 8, a threads cap; the server is not started while off |
| Mixed embedding spaces across devices | `space_id` on every vector and sync op; never index foreign spaces |
| Spanish quality lower than English | The research doc's model choice is weighted on MMTEB multilingual + Spanish evidence; the opt-in recall test has a Spanish fixture |
| License drift (model card changes license later) | The pin is to a commit; the LICENSE is copied at pin time into `infrastructure/models/licenses/`; re-check at each bump |
| Gemma-terms obligations (if chosen) | D2; the notice and use-policy link shown before download |
| Long PDFs slow indexing | 16-chunk cap, first pages first, the indexing state is visible |

## Decisions for the owner

- **D1 — Default model.** Recommended: EmbeddingGemma 2 text Q8_0 (310 MB, Apache-2.0). Fallback: Qwen3-Embedding-0.6B Q8_0 (639 MB, over the ~500 MB guideline). Alternatively nomic-embed-text-v2-moe Q6_K (397 MB, 512-token context) if 500 MB is a hard ceiling.
- **D2 — License posture.** EmbeddingGemma 2 is Apache-2.0, but its card adds "Deployments must adhere to the Gemma Prohibited Use Policy". Have counsel confirm that this line is acceptable, and decide whether Bento's terms should link the policy. The older Gemma Terms of Use models (EmbeddingGemma-300m) stay excluded.
- **D3 — Download source.** HF pinned commit first with a GitHub-release mirror as fallback (recommended), HF only, or Bento mirror only. The mirror means Bento redistributes the model (licenses allow it) and pays the egress.
- **D4 — Binary distribution.** Build and sign `llama-server` ourselves and bundle it in each installer (recommended; +12-25 MB), or re-sign the official archives, or download it on activation (not recommended: Gatekeeper, SmartScreen and a supply-chain cost).
- **D5 — Image search path.** Recommended: v1 text-only (OCR + metadata) now, then the EmbeddingGemma 2 mmproj add-on (+555 MB) after the #30195 spike, with SigLIP2 ONNX as plan B. Choose the v2 path from the research options, or defer it. A caption-based path conflicts with the "no automatic captions" non-goal in `orchestration/README.md`. Choosing it means amending that line, for example to "captions only as an internal search signal, never shown or synced as content".
- **D6 — Android.** Keep it off (v1, recommended for now), or fund the Stage 26 query-only spike.
- **D7 — sqlite-vec.** Add it to the desktop bundle now, or keep the Python fallback until libraries exceed ~50 k vectors.
- **D8 — Defaults.** Smart search stays opt-in (recommended), or is suggested in onboarding on machines with ≥ 4 cores and 8 GB RAM, as OCR already is.
- **D9 — Matryoshka dims.** Full dims (best quality) or truncated (for example 256: ~3× smaller index, faster brute force, small recall loss).

## Status

Planned (2026-11-26). Nothing implemented. Research: `research/embedding-models-2026.md`.
