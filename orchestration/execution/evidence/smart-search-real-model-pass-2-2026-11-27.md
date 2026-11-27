# Smart search: second real-model pass (Linux, 2026-11-27)

Second manual pass for `execution/smart-search-program.md` §Stage 25 Exit, following the method of `smart-search-real-model-2026-11-26.md`. It used the **real** pinned model (EmbeddingGemma 2 Q8_0, downloaded again from Hugging Face through the product flow) and the **real** pinned `llama-server`. The tested code is `main` at `c176b49b`, which includes PR #13 (activation without restart, live indexing progress) and PR #14 (768-dim default, `.txt`/`.md`/`.csv` and PDF text-layer extraction without OCR, the `.txt` state fix). OCR was **disabled**, the desktop default.

**Verdict: exit-ready on Linux.** Both blockers from the first pass are fixed. Activation and removal took effect with no process restarted, twice. Indexing progress rose steadily from 0 to N, and `ready` came 36-57 ms after the last embedding job. The active space is 768 dims. Document text from `.txt`, `.md`, `.csv` and text-layer PDFs is found by FTS before activation and by meaning after it. Files uploaded after `ready` were embedded within about 1 s, with no `Invalid asset processing state transition`.

This pass found one search bug outside smart search and fixed it here (bug 1): with OCR off, an image could not be found by its file name once enough newer files existed. The ranking findings (2-4) are documented, not fixed. Neither pass covered the "pull the network cable" step of the Stage 25 exit; the first pass used a worker SIGKILL as a stand-in.

## Machine and versions

| Item | Value |
|---|---|
| CPU / RAM | AMD Ryzen 7 5800H (8 cores / 16 threads), 15 GiB RAM (about 8 GiB in use by other work during the run), NVMe |
| OS | Linux 7.2.15-6-omarchy (Arch-based), x86_64 |
| Network | home connection, 2.0-2.1 MB/s from Hugging Face |
| Backend | Python 3.13.15 (uv venv, `--extra desktop --extra dev`), FastAPI 0.165.0, SQLAlchemy 2.0.51, pypdfium2 4.30.0, sqlite-vec 0.1.6 (`vec_version()` = `v0.1.6`) |
| llama.cpp | `b12777`. The `dist/llama-server/linux-x64/` built for the first pass was copied in, not rebuilt. `llama-server --version` → `version: 1.1.0-dev (build 12777, commit caea914e9)`. Every file matched `SHA256SUMS`, and `scripts/build-llama-server.sh` reported the copy "up to date", so its fingerprint (tag, source SHA-256, target, CMake flags) matches the pin |
| Model | `ggml-org/embeddinggemma-2-GGUF@6ea3e3a309d12a4779cfda98b8c19800d2d5da71`, `embeddinggemma-2-Q8_0.gguf`, 309,855,456 B, downloaded twice |

Run setup: `DATA_DIR=~/.cache/bento-e2e2/data`, `BENTO_RUNTIME_MODE=headless`, `HOST=127.0.0.1`, `API_PORT=18744`, `STORAGE_BACKEND=local`, `OCR_PROVIDER=disabled`, `WORKER_CONCURRENCY=1`, `BENTO_LLAMA_SERVER_PATH=<worktree>/dist/llama-server/linux-x64/llama-server`. There was no `.env`, no Telegram variable and no `EMBEDDINGS_PROVIDER` (so `locked: false`). The processes were `python -m bento.interfaces.desktop.launcher {migrate,api,worker}`. A poller sampled `GET /api/smart-search` and the `llama-server` RSS every 0.5 s (1,350 samples). Requests carried `X-Bento-Client: web`. There was no web UI in this pass.

## Corpus

37 files, generated for the run, plus 2 uploaded after `ready`. The PDFs with a text layer were written with `tests/fakes/pdf_documents.py` (Helvetica with WinAnsi encoding, so Spanish accents and «ñ» round-trip). The scanned-like PDFs and PNGs were rendered with Pillow and have no text layer.

| Type | Count | Examples |
|---|---|---|
| PDF with a text layer | 19 (one with 2 pages) | electricity, water, gas and phone bills (es/en), recipes, travel, budget meeting notes (es/en), a rental contract, an annual revenue report, and `doc-2026-0417.pdf` (a vet visit: «vacuna antirrábica», «perro») whose name says nothing |
| PDF without a text layer | 2 | `escaneo-recibo-electricidad-marzo.pdf`, `scan-0093.pdf` (a washing machine warranty) |
| PNG | 3 | `endesa-recibo-abril.png`, `captura-whatsapp-cena.png`, `ticket-supermercado.png` |
| `.txt` | 6 | `apuntes.txt` («La contraseña del wifi es …»), `notes-0312.txt` (mortgage renewal at a fixed interest rate), a packing list, a shopping list, gift ideas, a diary entry |
| `.md` | 4 | moving plan, project roadmap, tortilla recipe, hiking notes |
| `.csv` | 3 | household expenses, reading list, storage-room inventory |
| After `ready` | 2 | `nota-taller.txt` (brake pads and an oil change), `doc-2026-0601.pdf` (a speeding fine) |

The 37 uploads took 9.5 s. Within 20 s the worker had run 34 `text_extract` jobs (19 + 2 PDFs and 13 text files) and 24 thumbnails, and all 37 assets were `indexed`. `asset_text` held 33 `document` rows: one per non-empty PDF page and one per text file. The 2 scanned PDFs stored no text.

## Results

| # | Step | Result | Timing / measurement |
|---|---|---|---|
| 1 | Reuse the pinned `llama-server` | PASS | Copied 43 MB. The fingerprint and `SHA256SUMS` matched (see Machine); not rebuilt |
| 2 | Fresh stack, smart search off | PASS | `/api/health` → `storage_backend: local, telegram_configured: false`. `GET /api/smart-search` → `off`, `locked: false`, `suggest_in_onboarding: true`, model `dims: 768` |
| 3 | FTS before activation finds document content | PASS | `indexed_text` hits from file bodies: «vacuna» → `doc-2026-0417.pdf`, «guanciale» → `receta-pasta-carbonara.pdf`, «bechamel» → `receta-lasana-verduras.pdf`, «Gaviota» and «contraseña del wifi» → `apuntes.txt`, "mortgage interest rate" → `notes-0312.txt`, «tienda de campaña» → `inventario-trastero.csv`, "offline sync" → `project-roadmap.md`, «tensión» → `diario-2026-02.txt`. Text in the scanned PDF («garantía») and in the PNGs («Mercadona») is not found, as expected with OCR off |
| 4a | Activate through the API, no restart | PASS | `POST /api/smart-search/activate {}` → `downloading`, space `embeddinggemma-2-q8_0@6ea3e3a3…/768`. Bytes flowed at t+2.9 s |
| 4b | Download → verifying → starting | PASS | Download finished at about t+155.5 s (2.0 MB/s). In round 1 `verifying` lasted less than one 0.5 s sample. In round 2 it was seen for 0.5 s. `starting` at t+155.8 s. The server was ready at t+157.0 s (`started_at` in `embedder.json`) |
| 4c | Indexing with live progress | PASS | `indexing 0/37` at t+158.2 s, then 2, 5, 8, 11, 14, 17, 19, 21, 23, 25, 29, 32, 35 of 37, one sample every 0.6 s. Progress and `bytes_done` never went down across all 1,350 samples |
| 4d | `ready` right after the last job | PASS | Last embedding job at 05:50:18.285 UTC, status `ready` at 05:50:18.321 (36 ms later). The fallback `wait` job, due at 05:51:09, was closed at 05:50:18.338 without running. The first pass waited about 60 s here |
| 4e | 768-dim space | PASS | `embedding_spaces` row `…/768`, `dims 768`, `active`. Each chunk vector is 3,072 B (37 chunks = 113,664 B). `vec0` table `asset_embedding_vec_49f04615` |
| 4f | API follows the activation | PASS | Searches returned `semantic` hits with no API restart. `GET /api/settings` → `embeddings_state: ready`, `model_available: true` |
| 4g | Runtime hardening | PASS | Same as the first pass: `run/` 0700, `embedder.json` and the key file 0600, `base_url: http+unix://…/run/embedder-02a93cae.sock`, no TCP listener (`ss -ltnp`). Flags `--embeddings --pooling mean -c 2048 -ub 2048 -b 2048 -np 1 -t 4 -tb 4 --no-ui --offline` |
| 5 | Searches (next section) | PASS | Latency 50-85 ms warm (3 runs over 11 queries, median about 54 ms). The first search after activation took 351 ms, presumably while the API rebuilt its search wiring |
| 6 | Upload a `.txt` and a PDF after `ready` | PASS | Both uploads, `text_extract` and `embedding` jobs succeeded, with the `embedding` job finished 0.9 s (PDF) and 1.0 s (`.txt`) after upload. No `Invalid asset processing state transition` in either log. «freno del coche» → `nota-taller.txt` #1 and «multa de velocidad» → `doc-2026-0601.pdf` #1, both `semantic` + `indexed_text`. The status stayed `ready` with 37/37 (new uploads do not go through re-embedding) |
| 7a | Remove the model (`DELETE /api/smart-search/model`) | PASS | → `off`. `llama-server` was gone within 0.5 s. `models/` and `run/` were empty, and `model_installs` was empty. Within one 30 s janitor sweep, `asset_embedding_chunks` and `asset_embeddings` were empty, the `vec0` table was dropped and the space was `retired`. `embeddings_provider` went back to `disabled` |
| 7b | FTS after removal | PASS | «vacuna», «contraseña del wifi», "mortgage interest rate", «pastillas de freno», «multa» and «receta de pasta» all still found their files by `indexed_text`, with 6-26 ms latency |
| 7c | Activate again, no restart | PASS | The product downloads again, because removal deleted the files: 146 s at 2.1 MB/s. `verifying` at t+146.7 s, `starting` at t+147.2 s, `indexing` at t+148.5 s, then 1, 3, 6 … 36 of 39, then `ready` at t+157.9 s. The last job came 57 ms before `ready`. The `retired` space with the same id became `active` again, with 39 chunks |
| 7d | Remove again (cleanup) | PASS | Same as 7a |
| 8 | Opt-in `pytest -m real_model` at the 768 default | PASS | Server ready in 1.32 s, the 200-doc fixture indexed in 17.8 s, query p50 22.9 ms. The test now asserts its 0.75 floor on 768. Recall@5 and MRR are identical to the first pass at every dimension (table below) |

### Measurements

| Item | Value |
|---|---|
| `llama-server` RSS | 502 MiB peak (514,240 KiB, round 1 indexing). 480 MiB (491,648 KiB) after round 2 indexing. The first pass measured 492 MiB at 512 dims. The dimension does not change the model, so this is the same within noise |
| Indexing throughput | Round 1: 37 files in 8.3 s, 4.4 files/s. Round 2: 39 files in 8.5 s, 4.6 files/s. Each file is 1 chunk. The first pass measured 6.8 files/s, and its real-model test indexed 200 docs in 13.6 s against 17.8 s now. The 768 dims cannot explain that: the model computes 768 dims and smaller spaces truncate afterwards. The machine was busier during this pass (8 of 15 GiB in use), so this is load, not a regression, but it was not isolated |
| Vector storage at 768 | 3,072 B per chunk in `asset_embedding_chunks` and again in `vec0`. Measured with `dbstat` for 39 chunks: `asset_embedding_chunks` 163,840 B of pages; `vec0` `vector_chunks00` 3,149,824 B, which is one preallocated block of 1,024 vectors × 3,072 B, so it does not grow until vector 1,025. At scale that is about 6 KiB per chunk, against 4 KiB at 512 dims: about 60 MB for 10,000 one-chunk files, and up to 16× that for long documents |
| Disk | Data dir 314.5 MB at `ready`, 309.9 MB of it the model. After removal 4.6 MB. The DB keeps 826 free pages of 4 KiB (3.4 MB, mostly the `vec0` block), the same open point as note 5 of the first pass |

### Search results (top 6 at `ready`; flags are `match_reasons`)

| Query | Results |
|---|---|
| «facturas de luz» | 1 factura-luz-febrero-2026 · 2 factura-luz-enero-2026 · 3 ideas-regalos-navidad.txt (file name contains «de») · 4 gastos-hogar-2026.csv (semantic) · 5 factura-gas-natural-febrero (semantic) · 6 escaneo-recibo-electricidad-marzo (semantic, by file name, no text layer) |
| «receta de pasta» | 1 receta-pasta-carbonara · 2 receta-lasana-verduras · 3 pesto-pasta-recipe (en) · 4 receta-tortilla.md · 5 receta-gazpacho · 6 ideas-regalos-navidad.txt |
| «viaje a la playa» | 1 viaje-cadiz-playa-agosto · 2 packing-list-beach.txt (en) · 3 diario-2026-02.txt · 4 plan-mudanza.md · 5 reserva-hotel-mallorca · 6 ideas-regalos-navidad.txt. Ranks 3, 4 and 6 come from file-name substrings («a», «de») |
| "electricity bill" (en → es) | 1 electric-bill-october-2025 · 2 phone-bill-january · **3 factura-luz-enero-2026 · 4 factura-luz-febrero-2026 · 5 escaneo-recibo-electricidad-marzo · 6 gastos-hogar-2026.csv** (semantic only) |
| «reunión de presupuesto» (es → en) | 1 notas-reunion-presupuesto-q3 · **2 budget-meeting-minutes** (semantic only) · 3 ideas-regalos-navidad.txt · 4 gastos-hogar-2026.csv · 5 phone-bill-january · 6 inventario-trastero.csv |
| "beach holiday" (en → es) | 1 packing-list-beach.txt · 2 beach-vacation-itinerary-hawaii · **3 viaje-cadiz-playa-agosto · 4 reserva-hotel-mallorca** (semantic only) · 5 hiking-notes.md · 6 phone-bill-january |
| «vacuna del perro» (PDF body only) | **1 doc-2026-0417.pdf** (semantic). FTS alone found nothing: «del» is not in the text |
| «contraseña del wifi» (`.txt` body only) | **1 apuntes.txt** (semantic + indexed_text) · 2 lista-compra.txt · 3 gastos-hogar-2026.csv … |
| "mortgage interest rate" (`.txt` body only) | **1 notes-0312.txt** (semantic + indexed_text) · 2 annual-revenue-report-2025 … |
| «freno del coche» (after upload) | **1 nota-taller.txt** (semantic + indexed_text) |
| «multa de velocidad» (after upload) | **1 doc-2026-0601.pdf** (semantic + indexed_text) |

The documents each query targets led its list, and every body-only query put its document first. Not every relevant file made the top 6: for «facturas de luz», `endesa-recibo-abril.png` (embedded by file name only, OCR off) and the English `electric-bill-october-2025` did not. The weak spots are FTS substring matches on short words above relevant semantic hits (finding 3), and filler at the bottom of every list (finding 2). "car brakes repair" put `receta-pasta-carbonara` (file name «car…») above `nota-taller.txt`, and "speeding ticket" put `ticket-supermercado.png` above `doc-2026-0601.pdf`; the right document was #2 both times.

### Real-model test at 768 (default, D9)

| Dims | recall@5 | MRR |
|---|---|---|
| **768 (default)** | **0.983** | **0.983** |
| 512 | 0.950 | 0.930 |
| 256 | 0.917 | 0.885 |
| 128 | 0.883 | 0.875 |

## Bugs found

### 1. With OCR off, images could not be found by file name in a library of more than a few dozen files (fixed in this PR)

`CompositeSearchIndex._add_metadata_hits` loaded the newest `candidate_limit` assets, then checked their names in Python. `candidate_limit` is `max(limit + 25, 3 × limit)`: 31 for `limit=6` and 125 for the web's `limit=50`. An asset with an `asset_fts` row can still be found through FTS. With OCR off, only assets that went through `text_extract` get that row (production never calls `index_asset`), so images, videos and other files are found by name only through this path. Once more than 125 newer files exist, they can no longer be found by name.

Reproduced live with 39 files and smart search off: «endesa» and «captura» returned nothing at `limit=6` and the image at `limit=50`. The same cause explains why `beach-vacation-itinerary-hawaii.pdf` (the 35th newest) lost its `filename` reason below `limit=10`.

Fix: the query now applies the limit to rows whose `filename`, `original_filename`, `mime_type` or EXIF JSON contain a token in SQL, and keeps scoring them with `_metadata_match`. The newest window is still scanned as before, because SQLite's `lower()` folds ASCII only (a name such as «AÑO» still matches «año» there). Regression: `test_filename_match_finds_an_asset_older_than_the_candidate_window` (60 newer images, `limit=6`). After restarting the API on the fix, «endesa», «captura», «ticket» and «recibo» found their images. Local CI backend: 1912 passed (`c168d6b1`).

Not changed: images still have no `asset_fts` row while OCR is off, so FTS ranking does not see their names. That only affects ranking now. A fix would index metadata at upload, for example by calling `index_asset` from the completion path, with a backfill.

### 2. Every asset becomes a `semantic` hit; there is no similarity floor (not fixed)

The vector search returns the `candidate_limit` nearest chunks with no minimum score, and each of them is flagged `semantic`. In a small library, every file shows up for every query. Fused scores for "beach holiday": 0.81 and 0.80 for the two beach files, 0.46 for both Spanish travel files, then 0.43-0.44 for a phone bill, an inventory and a warranty scan. A nonsense query ("zzzz quantum chromodynamics") returned 10 `semantic` hits at 0.41-0.44. With this model the noise floor is about 0.40-0.44, and real cross-language matches start at about 0.46. Those are close, so a single absolute cut-off needs care.

Suggested fix (needs calibration, so not done here): drop semantic-only candidates below a floor taken from the real-model fixture, such as the 95th percentile of non-relevant similarities, or below a margin under the best vector hit. Measure it with `pytest -m real_model` at every dimension, then record the value in `research/embedding-models-2026.md`.

### 3. FTS-side substring matches outrank relevant semantic hits (not fixed, as in the first pass)

`_metadata_match` uses `token in filename`, so «de» matches `i-de-as-regalos…` and `en-de-sa…`, «a» matches nearly every name, and "car" matches `carbonara`. These hits carry a `text_score` and sit above semantic-only hits: «facturas de luz» ranks `ideas-regalos-navidad.txt` #3, and "car brakes repair" ranks the carbonara recipe #1. The first pass noted the same pattern (its note 2). Suggested fix: match whole tokens or token prefixes of at least 3 characters on file names, and skip a small stop-word list (es/en) in name matching.

### 4. Chunks span PDF pages and record no page (not fixed, small contract gap)

`SQLiteEmbeddingTextCatalog.text_for_asset` joins all text rows into one string, and `EmbeddingIndexingService._chunks_for_asset` calls `chunk_text`. The 2-page contract therefore produced one chunk with `page = NULL`. `api/smart-search-contract.md` §Document text and §Chunking say that windows never span pages and that the chunk keeps its page. Nothing reads `page` yet except sync snapshots, so nobody can see this today. Suggested fix: return the document pages from the catalog (a `pages_for_asset` method, or `(page, text)` rows) and call `chunk_pages`. It changes the catalog port and the embedding service, owned by Stage 24 embeddings-runtime.

## Fixed since the first pass (confirmed)

- First-pass bug 1 (activation needs a restart): fixed by PR #13. Two activations and two removals took effect with the API and the worker running the whole time.
- First-pass bug 2 (progress frozen at 0, `ready` about 60 s late): fixed by PR #13. Progress moved every sample, and `ready` came 36 ms and 57 ms after the last job.
- First-pass note 3 (`.txt` and PDF text layers not indexed without OCR): fixed by PR #14 (step 3 and the body-only queries).
- The `.txt` `Invalid asset processing state transition` (PR #14): it did not occur for 6 `.txt`, 4 `.md` and 3 `.csv` files embedded at activation, nor for the `.txt` uploaded after `ready`.

## Not verified here

- A real network drop during the download (`waiting_network`, resume after reconnect). Neither pass did it; the first pass used a worker SIGKILL.
- Pause, resume and cancel. The first pass covered pause and resume; this pass did not repeat them.
- The web UI (activation sheet, progress announcements, remove dialog); macOS, Windows, packaged desktop builds and the CLI daemon.
- «fotos de la playa» from the Stage 25 exit: this corpus has no photos with content, and with OCR off, images are only embedded by file name.
- A large library (thousands of files): indexing time, RAM and vector storage beyond the first `vec0` block.

## Cleanup

All processes started for this pass were stopped: API, worker, `llama-server` and the poller. The model was removed through the API, and the throwaway data dir and corpus (`~/.cache/bento-e2e2`) were deleted. Kept: `dist/llama-server/linux-x64/` in this worktree (43 MB, git-ignored).
