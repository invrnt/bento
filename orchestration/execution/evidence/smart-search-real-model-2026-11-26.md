# Smart search: Stage 25 exit check with the real model (Linux, 2026-11-26)

Manual pass required by `execution/smart-search-program.md` §Stage 25 Exit. It used the **real** pinned model (EmbeddingGemma 2 Q8_0, downloaded from Hugging Face) and a **real** `llama-server` built by `scripts/build-llama-server.sh`. The API and worker ran as separate `bento-sidecar` processes on a throwaway data dir with `STORAGE_BACKEND=local` (no Telegram account). The tested code is `main` at `ad957784` (PR #12).

**Verdict: not exit-ready.** The download, verification, runtime, indexing, search and removal all work with the real model and binary. But activation **does not take effect until the API and the worker restart** (bug 1). Nothing in the desktop host, the CLI daemon or the web UI restarts them. A person who turns the feature on from Settings stays at "Preparando…" forever. Bug 2 (indexing progress frozen at 0 until the end) breaks the progress and announcement contract.

## Machine and versions

| Item | Value |
|---|---|
| CPU / RAM | AMD Ryzen 7 5800H (8 cores / 16 threads), 15 GiB RAM, NVMe |
| OS | Linux 7.2.15-6-omarchy (Arch-based), x86_64 |
| Network | home connection, about 1 MB/s from GitHub and 2-3 MB/s from Hugging Face during the run |
| Toolchain | GCC 16.2.1, CMake 4.4.5, Python 3.13.15 (uv venv, `--extra desktop --extra dev`), Node 26.13.1 |
| Backend libs | FastAPI 0.165.0, SQLAlchemy 2.0.51, onnxruntime 1.29.0, RapidOCR 3 (bundled PP-OCRv6 models), sqlite-vec 0.1.6 (`vec_version()` = `v0.1.6`, loaded) |
| llama.cpp | `b12777`, `llama-server --version` → `version: 1.1.0-dev (build 12777, commit caea914e9)`, `built with GNU 16.2.1 for Linux x86_64` |
| Model | `ggml-org/embeddinggemma-2-GGUF@6ea3e3a309d12a4779cfda98b8c19800d2d5da71`, `embeddinggemma-2-Q8_0.gguf`, 309,855,456 B |

Run setup: `DATA_DIR=~/.cache/bento-e2e/data`, `BENTO_RUNTIME_MODE=headless`, `HOST=127.0.0.1`, `API_PORT=18734`, `OCR_PROVIDER=rapidocr`, `BENTO_LLAMA_SERVER_PATH=dist/llama-server/linux-x64/llama-server`; no `.env`, no Telegram variables, and no `EMBEDDINGS_PROVIDER`, so the feature was not locked. The processes were `python -m bento.interfaces.desktop.launcher {migrate,api,worker}`, run directly rather than through the CLI daemon so the worker could be killed on its own. The web UI was the Vite dev server (`VITE_API_BASE_URL`, `WEB_PORT=15173`), driven in the T3 preview browser.

## Results

| # | Step | Result | Timing / measurement |
|---|---|---|---|
| 1 | Build `llama-server` with `scripts/build-llama-server.sh` | PASS | 312 s wall (16 jobs), including about 35 s to download the 38 MB source tarball. The SHA-256 `d7f875b8…19cd8c` was verified before extracting. Output `dist/llama-server/linux-x64/` is 43 MB: the 16 KB `llama-server`, `libllama*`, `libmtmd`, 14 `libggml-cpu-*` variants, `licenses/`, `bento-llama-server.json` and `SHA256SUMS` |
| 2 | Fresh stack (migrate, API, worker), local storage, desktop extra | PASS | API healthy in about 2 s; `/api/health` → `storage_backend: local, telegram_configured: false` |
| 3a | `GET /api/smart-search` before activation | PASS | `state: off`, `suggest_in_onboarding: true` (16 logical CPUs, 15 GiB ≥ D8 thresholds), `locked: false`, model `EmbeddingGemma 2 · Apache-2.0 · 309,855,456 B · huggingface.co · 512 dims` |
| 3b | Seed corpus through `POST /api/assets/upload` | PASS | 36 files: 31 single-page PDFs, 2 PNGs and 4 `.txt`, covering es/en electricity, water, gas and phone bills, recipes, travel, work notes and contracts. OCR (RapidOCR) indexed all 36 in about 60 s |
| 3c | Activate → real download starts | PASS | `POST /activate` → `downloading` with the space `embeddinggemma-2-q8_0@6ea3e3a3…/512`. Bytes flowed within 1 s |
| 3d | Pause partway, then resume | PASS | Paused at t+51 s at 83,886,080 B; the `.part` stayed at 83,886,080 B for 11 s. Resume (t+70 s) continued from 83,886,080 B (`If-Range` ETag kept in `.part.meta`), with no restart from zero |
| 3e | Kill the worker (SIGKILL) mid-download, restart it | PASS | Killed at t+103 s with `.part` = 161,808,384 B. The job was left `running`. On restart (t+116 s) the worker logged "Requeued 1 jobs left running by a previous worker", and the first sample after restart was 160.7 MB, then rising. `bytes_done` never decreased across the run |
| 3f | Verify → starting → indexing → ready | PASS **only after a worker restart** (bug 1) | Download finished at t+185 s; verifying took about 2 s; the SHA-256 of the file is `2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135`, equal to the manifest. Starting took under 1 s (server ready in about 0.7 s). Indexing 36/36 took 60.4 s to `ready` (t+247 s), but only 5.3 s of that was embedding work (bug 2). In round 2 (worker not restarted after activation) the status stayed at `starting` for 200 s and no `llama-server` was spawned |
| 3g | Search («facturas de luz», «receta de pasta», «viaje a la playa», 3 cross-language) | PASS **only after an API restart** (bug 1) | Before the API restart: FTS results only, and `GET /api/settings` said `embeddings_state: disabled`. After it: `semantic` hits in every query, ranked sensibly (below). Latency 30-60 ms warm, 160 ms for the first query after an API start |
| 3h | `embedder.json` mode, Unix socket | PASS | `run/` is 0700, `embedder.json` 0600, `embedder-<id>.key` 0600, and `base_url: http+unix://…/run/embedder-<id>.sock`. The server ran with `--host <socket> --api-key-file <0600 file> --no-ui --offline -np 1 -c 2048 -ub 2048 -b 2048 -t 4 -tb 4 --pooling mean`, with no TCP listener (`ss -ltnp`). The key never appeared in logs |
| 3i | Remove the model (round 1 from the web UI, round 2 with `DELETE /api/smart-search/model`) | PASS | The UI showed a destructive confirm dialog, focused on "Keep it"; after confirming it showed `Off`. `llama-server` exited 1.6 s after the DELETE. `models/` and `run/` were empty, and `model_installs` was empty. The worker janitor dropped `asset_embedding_chunks`, `asset_embeddings` and the `vec0` table within one 30 s sweep, and the space became `retired`. `embeddings_provider` went back to `disabled` |
| 3j | Disk back to baseline | PASS (with a note) | 7.03 MB before activation, 319.3 MB at ready, 9.44 MB after removal. The 2.4 MB left over is 564 free SQLite pages (no `VACUUM` after the vectors are dropped). The live data is at baseline (see note 5) |
| 3k | Search after removal | PASS | FTS only, identical to the pre-activation baseline for all six queries |
| 3l | Web UI in the browser | PASS (partial) | The Settings › Smart search panel rendered `Ready` with "EmbeddingGemma 2 · 296 MB on this computer" and "Remove the model and free 296 MB". The remove flow is in 3i. The preview could not take screenshots (hidden tab), so the DOM was read instead. Activation through the sheet was not driven in the UI; it went through the API |
| 4 | Opt-in `pytest -m real_model` (30 cross-language queries) | PASS | Server ready 0.71 s, 200-doc fixture indexed in 13.6 s, query p50 19.8 ms. Results in the next section |
| — | `llama-server` RSS | — | 492 MiB (503,984 KiB), the same at idle and at the highest sample during indexing, with `-np 1 -c 2048` |
| — | Indexing throughput | — | 36 short documents (1 chunk each) in 5.3 s of embedding jobs, about 6.8 files/s through the worker; the real-model test embedded 200 docs in 13.6 s (about 15 docs/s, no job queue) |

Download wall time: 185 s in round 1 (with an 18.6 s pause and a 13 s worker gap), 155.7 s in round 2 (uninterrupted, about 2.0 MB/s).

### Search results (top 6, after the API restart; `semantic` = vector hit)

| Query | Results |
|---|---|
| «facturas de luz» | 1 factura-luz-febrero-2026 · 2 factura-luz-enero-2026 · 3 endesa-recibo-abril (PNG) · 4 ideas-regalos-navidad.txt · 5 evaluacion-desempeno-2025 · 6 factura-gas-natural-febrero. FTS alone ranked none of the electricity bills in its top 6 (it matched on «de») |
| «receta de pasta» | 1 receta-pasta-carbonara · 2 receta-lasana-verduras · 3 receta-macarrones-tomate · 4 pesto-pasta-recipe (en) · 5 receta-tortilla-patatas · 6 receta-gazpacho |
| «viaje a la playa» | 1 viaje-cadiz-playa-agosto · 2 beach-vacation-itinerary-hawaii (en) · 3 packing-list-beach.txt · 4 reserva-hotel-mallorca · 5 billete-avion-madrid-tenerife |
| "electricity bill" (en → es) | 1 electric-bill-october-2025 · 2 phone-bill · 3 billete-avion (FTS prefix «bill*») · 4 power-utility-statement-nov · 5-8 factura-luz-enero, endesa-recibo-abril, factura-luz-febrero, recibo-electricidad-marzo (semantic only) |
| «reunión de presupuesto» (es → en) | 1 notas-reunion-presupuesto-q3 · **2 budget-meeting-minutes** (semantic only) |
| "beach holiday" (en → es) | 1 beach-vacation-itinerary-hawaii · 2 packing-list-beach.txt · **3 viaje-cadiz-playa-agosto · 4 reserva-hotel-mallorca** (semantic only) |

The vector part ranks the right documents. The hybrid ranking still lets weak FTS matches (prefix «bill*», «de», `.txt` file names) sit above relevant semantic-only hits. The `.txt` files only ever match by file name (note 3).

### Real-model test: cross-language recall at each dimension

| Dims | recall@5 | MRR |
|---|---|---|
| 768 | 0.983 | 0.983 |
| **512 (default, D9)** | **0.950** | **0.930** |
| 256 | 0.917 | 0.885 |
| 128 | 0.883 | 0.875 |

These are per-query ranks of the first relevant document; only the queries whose rank is not 1 at every dimension are listed:

| Direction | Query | 768 | 512 | 256 | 128 |
|---|---|---|---|---|---|
| en→es | mortgage deed | 1 | 3 | 6 | 23 |
| en→es | income tax return | 1 | 1 | 2 | 2 |
| es→en | informe trimestral de ingresos | 2 | **14** | 27 | 15 |
| es→en | receta de tortitas esponjosas | 1 | 1 | 1 | 2 |
| es→en | postre de chocolate | 1 | 1 | 2 | 8 |
| es→en | informe anual de ingresos | 1 | 2 | 3 | 1 |

**Gap at 512 vs 768:** 27 of 30 queries rank the same, 3 rank worse, and none rank better. Only one query leaves the top 5 (es→en «informe trimestral de ingresos», 2 → 14). This is the same pattern as the Stage 23 spike (one es→en query). The loss is small (−3.3 points recall@5, −5.3 points MRR) but always in the same direction. The test is still well above its 0.75 floor. Whether this counts as the "consistent cross-language gap" that D9 says would justify 768 is an owner call. The case for 768 is weak on recall but real on MRR; the cost is 1.5× the vector storage.

## Bugs found

### 1. Activation never takes effect without restarting the API and the worker (blocker, not fixed)

`POST /api/smart-search/activate` writes `embeddings_provider = managed` through `EditableSettingsService`. That setting is `Apply.RESTART_SERVICES`, but no process restarts:

- **Worker**: `run_worker()` builds the embedding runtime once, from the settings at startup (`_worker_embedding` → `build_worker_embedding`). With `disabled` it has no runtime and `WorkerSmartSearchHooks.starting()` is a no-op. The download and verification still run, then the status stays at `starting` forever, with no `llama-server` spawned. Reproduced in round 2: 200 s at `starting`, then a worker restart moved it to `indexing` → `ready` in 63 s.
- **API**: `routes_search._search_dependencies()` caches the query provider in `app.state` on the first search, and `app.state.settings` is fixed at startup. Searches stay FTS-only, and `GET /api/settings` keeps saying `embeddings_state: disabled`, while `/api/smart-search` says `ready` with `search_available: true`.
- **Who could restart**: desktop restarts sidecars only inside `settings-transaction.ts`, the Electron IPC settings flow, and the activation route bypasses it. The web smart-search hooks call no restart. The CLI daemon only restarts children that crash. Round 1 reached `ready` only because the worker kill test restarted the worker after activation.
- **Removal**: the same gap exists in reverse, but it is harmless. The runtime notices the `off` status and stops the server, and the janitor drops the vectors. The API keeps a managed query provider that finds no `embedder.json` and falls back to FTS.
- **Suggested fix** (needs an owner because it spans api, worker, desktop and the CLI daemon; too large for this check):
  - Make the worker and the API derive "managed on/off" from the persisted smart search status, not from startup settings. The worker would always build the `SmartSearchRuntimeService`, which already reads the status every tick. The API would rebuild its search dependencies when the status's `space_id` or the effective `embeddings_provider` changes.
  - Or have activate/remove return a `restart_plan` that the desktop host and the CLI daemon honour.
  - Add an API test that activates against a worker built while `disabled`.

### 2. Indexing progress stays at "0 of N" until the end, and `ready` comes up to 60 s late (not fixed)

`ReembedService` reports progress only when its `reembed` check job runs. The check has `REEMBED_PRIORITY = EMBEDDING + 1` and `run_after = now + 60 s`, and the SQLite queue claims jobs by priority first. So the check can only run after **every** queued embedding job has drained, and only after its 60 s delay.

Measured: all 36 embedding jobs finished 5.3 s after the flip, but the status showed «Revisando tus archivos · 0 de 36» for 60 s and then jumped to `ready`. On a real library the bar stays at 0 % for the whole indexing run, so the 10 % live-region announcements in the product contract never fire.

Suggested fix: report progress from the embedding job completion (an increment on the status, keyed by `space_id`), or give the check its own cadence that does not wait behind the backlog. Then shorten the final delay, for example by scaling it with the pending count.

## Other observations (not bugs in the Stage 24/25 scope)

1. In headless mode `suggest_in_onboarding` was `true` on this 16-thread, 15 GiB machine, as specified by D8.
2. The FTS-only ranking of «facturas de luz» matches on the stop word «de» and on prefixes. It ranked travel and recipe PDFs first and none of the electricity bills in its top 6. This is the existing text search; smart search hides it, but the FTS fallback is weak for Spanish queries with function words.
3. Plain `.txt` content is never indexed, and PDF text layers are ignored. `OCRIndexingService` only handles images and PDFs, through OCR rendering, and `EmbeddingIndexingService` falls back to `filename + mime` when there is no OCR text. Text files are therefore searchable only by name, and with `OCR_PROVIDER=disabled` (the desktop default) PDFs are too. Smart search over documents effectively requires OCR on.
4. The UI label "296 MB" is 309,855,456 B shown in MiB (binary units under a "MB" label).
5. After removal SQLite keeps the freed vector pages: 564 pages of 4 KiB for 36 assets. At 512 dims × 4 B per chunk, up to 16 chunks per asset, plus the `vec0` copy, a library of 10 k documents could keep tens to hundreds of MB in the DB file until a `VACUUM`. Consider `PRAGMA incremental_vacuum` or a `VACUUM` after a space is retired, if the "free {size}" promise should hold for the DB as well.
6. The `.part`, the final GGUF, `LICENSE` and `NOTICE` are mode 0644 (not secrets). The socket is 0755 inside a 0700 `run/` directory.
7. The web UI rendered English strings although `<html lang="es">`. This is presumably locale detection from the browser; it was not investigated.

## Not verified here

- macOS and Windows; a packaged desktop build (`smoke-packaged.mjs`, `verify-artifacts.mjs` against this build); the CLI daemon path (`bento daemon run`).
- A real network drop (cable pulled, `waiting_network`, automatic reconnect). A SIGKILL of the worker stood in for it: that tests resuming from the `.part`, not the `network_lost` / `network_restored` sub-state or the backoff.
- The Hugging Face → GitHub mirror fallback (the mirror release does not exist yet).
- The `checksum`, `space` and `runtime` error paths and retry with the real binary; cancel mid-download; model update / "Usar ya".
- The activation sheet and pause/resume driven by keyboard in the browser. Only the ready state and the remove dialog were exercised in the UI.
- Battery / `power.json` pausing; a large library (thousands of files) for indexing time and RAM.

## Cleanup

All processes started for this check were stopped: API, worker, `llama-server`, Vite and the poller. The throwaway data dir and seed corpus (`~/.cache/bento-e2e`, including both model downloads) and the llama.cpp build tree were deleted. Kept: `dist/llama-server/linux-x64/` (43 MB, git-ignored) and the verified source tarball in `~/.cache/bento/llama.cpp/` (38 MB, reused by the next build).
