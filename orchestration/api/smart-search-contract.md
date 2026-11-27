# Smart Search Contract (Stage 23)

Binding contract between the Stage 24 backend agents and the Stage 25 web/desktop agents for "Buscar por significado". Program: `execution/smart-search-program.md`. Research and measurements: `research/embedding-models-2026.md`.

The pure rules live in `apps/api/src/bento/domain/smart_search.py`, the outbound ports in `ports/models.py` and `ports/providers.py`, and the tests in `apps/api/tests/unit/smart_search/`. The code is the source of truth when this page and the code disagree. A change to either goes through a handoff request to the Stage 23 owner.

Stage 23 adds no HTTP route, so `apps/android/core/api/openapi.json` does not change. Stage 24 (models-download) adds `routes_smart_search.py` exactly as specified here, re-exports the OpenAPI snapshot, and keeps the web types green.

## Endpoints

All endpoints are loopback-only like the rest of the API. Every response that carries a status uses the `SmartSearchStatus` body below.

| Method and path | Effect | Allowed from | Errors |
|---|---|---|---|
| `GET /api/smart-search` | Current status, model offer, free space | any | — |
| `POST /api/smart-search/activate` | `off → downloading`. Body `{"model_id"?: str, "dims"?: int}`; both default to the manifest's recommendation | `off` | `409 smart_search_state_conflict`, `400 invalid_model_spec` (unknown model or dims), `409 smart_search_no_space` with `details: {required_bytes, free_bytes}` (precheck: free < size + 10 %), `409 settings_source_locked` (env-controlled, the existing settings code) |
| `POST /api/smart-search/pause` | `downloading → paused` | `downloading` | `409` |
| `POST /api/smart-search/resume` | `paused → downloading` | `paused` | `409` |
| `POST /api/smart-search/retry` | `error → failed step`; after `checksum`, the download restarts from zero | `error` | `409` |
| `POST /api/smart-search/cancel` | Stops the work, deletes partial files, returns to `off` | `downloading`, `paused`, `verifying`, `starting`, `error` | `409` |
| `POST /api/smart-search/update` | Starts downloading the manifest's newer revision as a new space. The old space keeps serving search until the flip (§Re-indexing) | `ready` with `update_available` | `409` |
| `POST /api/smart-search/use-now` | "Usar ya": flips search to the space being re-embedded before it reaches 100 % (`ReembedService.use_now()`). The queued embedding jobs keep filling it; the status moves to the new space and the old model's files are deleted | `can_use_now` is `true` | `409` (no re-embed pending, `event: "use_now"`) |
| `DELETE /api/smart-search/model` | Stops the runtime, deletes the model files and the space's vectors, returns to `off` | any state except `off` | `409` |

`409` uses code `smart_search_state_conflict` with `details: {state, event}`. This maps `IllegalSmartSearchTransitionError` (code `illegal_smart_search_transition` in the domain). The new codes are added to `error-model.md` in Stage 24.

### `SmartSearchStatus` body

```json
{
  "state": "downloading",
  "waiting_network": false,
  "error_code": null,
  "failed_step": null,
  "space_id": "embeddinggemma-2-q8_0@6ea3e3a309d12a4779cfda98b8c19800d2d5da71/512",
  "download": {"bytes_done": 104857600, "bytes_total": 309855456},
  "indexing": {"done": 0, "total": 0},
  "model": {
    "model_id": "embeddinggemma-2-q8_0",
    "display_name": "EmbeddingGemma 2",
    "license_spdx": "Apache-2.0",
    "license_url": "/api/smart-search/license",
    "size_bytes": 309855456,
    "download_host": "huggingface.co",
    "dims": 512
  },
  "free_bytes": 52613349376,
  "update_available": null,
  "locked": false,
  "search_available": false,
  "can_use_now": false,
  "suggest_in_onboarding": false
}
```

- `state` is one of `off | downloading | paused | verifying | starting | indexing | ready | error`.
- `error_code` is one of `download | checksum | space | runtime`, set exactly when `state` is `error`. `failed_step` is the step that `retry` returns to.
- `waiting_network` is only ever `true` during `downloading`.
- `search_available` is `true` in `ready` and `indexing` (the active space serves queries while the backlog runs).
- `update_available` is `null` or `{"revision", "size_bytes", "progress"}`. The state machine has no update state, so the status stays `ready` while an update downloads. `progress` is `null` until `POST /update` started, then `{"bytes_done", "bytes_total", "state"}` from the newer revision's `model_installs` row, with `state` one of `downloading | verifying | installed | error`. `installed` means verified and re-embedding into the new space; after an `error` the update action starts again.
- `can_use_now` is `true` while search is available (`ready`/`indexing`) and a `building` space is pending: a verified update's space, or the status's own space while an older one still serves search. It is `false` when this process has no re-embed owner wired.
- `suggest_in_onboarding` (D8) is `true` when `state` is `off`, the feature is not `locked`, the platform is not Android, and `suggest_in_onboarding(cores, ram)` holds for this machine (≥ 4 cores and ≥ 8 GiB, read by the API with the standard library: `os.cpu_count()`, `sysconf(SC_PHYS_PAGES × SC_PAGE_SIZE)`, `GlobalMemoryStatusEx` on Windows). The UI only offers the confirmation sheet; nothing downloads without "Descargar y activar".
- `locked` is `true` when `BENTO_EMBEDDINGS_PROVIDER` or another env override controls the feature. The UI shows the switch read-only.
- `GET /api/settings` keeps `embeddings_state` and `model_available` for old clients. With `embeddings_provider = managed`: `embeddings_state` = `SmartSearchStatus.legacy_embeddings_state()` (`off → disabled`, `ready → ready`, `error → failed`, otherwise `pending`), and `model_available` = the status's weights file is installed and its verification marker matches. With `custom`, `model_available` is whether `custom_model_path` exists.
- Progress fields never carry paths, URLs with tokens, or request bodies.

`GET /api/smart-search/license` returns the Apache-2.0 text shipped in `infrastructure/models/licenses/` as `text/plain`.

## State machine

`transition(status, event)` in the domain is the only place that decides legality. Everything not in this table raises `IllegalSmartSearchTransitionError`. The unit tests enumerate every (state × event × error code) combination.

| From | Event | To | Notes |
|---|---|---|---|
| `off` | `activate` | `downloading` | sets `space_id`, `bytes_total` |
| `downloading` | `pause` | `paused` | clears `waiting_network` |
| `paused` | `resume` | `downloading` | keeps `bytes_done` |
| `downloading` | `network_lost` / `network_restored` | `downloading` | toggles `waiting_network` |
| `downloading` | `downloaded` | `verifying` | |
| `verifying` | `verified` | `starting` | |
| `starting` | `runtime_ready` | `indexing` (or `ready` after a runtime restart from `ready`) | |
| `indexing` | `indexed` | `ready` | |
| `ready` | `backlog(n)` | `indexing` if `n > 50`, else unchanged | no flicker for single uploads |
| `downloading` | `fail(download \| space)` | `error` | |
| `verifying` | `fail(checksum)` | `error` | the part file is already deleted |
| `starting`, `indexing` | `fail(runtime)` | `error` | |
| `ready` | `fail(runtime)` | `error`, `failed_step = starting` | after 5 restarts with backoff |
| `error` | `retry` | `failed_step`, or `downloading` from zero after `checksum` | |
| `downloading`, `paused`, `verifying`, `starting`, `error` | `cancel` | `off` | no residue on disk |
| any except `off` | `remove` | `off` | frees the model's bytes |

Per-asset embedding failures are not smart search errors. They keep the existing partial-failure asset states.

## Model manifest (`infrastructure/models/manifest.json`, schema 1)

`parse_manifest()` validates the file. Stage 24 ships it with exactly these two entries; the canonical copy is `apps/api/tests/unit/smart_search/manifest_v1.json`, except for the mirror URL, which `bento-release` fills in. Rules:

- `revision` is a hex commit id. Every URL is `https`, and Hugging Face URLs use `/resolve/<revision>/`.
- `sha256` is 64 lowercase hex characters (the HF LFS object id at pin time).
- File names are plain names with no path. Each model has exactly one `weights` file; `mmproj` is the Stage 26 add-on.
- `matryoshka_dims` includes `native_dims`, and `default_dims` is one of them.
- `0 < chunk_tokens ≤ ubatch_tokens ≤ context_tokens`.
- `query_template` contains `{q}`; `document_template` contains `{text}` and may contain `{title}`, which is filled with the file name or `none`.

| Field | EmbeddingGemma 2 (default, D1) | Qwen3-Embedding-0.6B (fallback) |
|---|---|---|
| `model_id` | `embeddinggemma-2-q8_0` | `qwen3-embedding-0.6b-q8_0` |
| `revision` | `6ea3e3a309d12a4779cfda98b8c19800d2d5da71` | `370f27d7550e0def9b39c1f16d3fbaa13aa67728` |
| weights | `embeddinggemma-2-Q8_0.gguf`, 309,855,456 B, `2188ac1d…40b09135` | `Qwen3-Embedding-0.6B-Q8_0.gguf`, 639,150,592 B, `06507c7b…49c3e439` |
| dims | native 768, MRL `[768, 512, 256, 128]`, **default 512** (D9) | native 1024, `[1024, 768, 512, 256]`, default 1024 |
| pooling | `mean` | `last` (the server appends EOS itself, verified in the spike) |
| context / ubatch / chunk | 2048 / 2048 / 512 | 2048 / 2048 / 512 |
| query | `task: search result \| query: {q}` | `Instruct: Given a search query, retrieve relevant files\nQuery:{q}` |
| document | `title: {title} \| text: {text}` | `{text}` |
| URLs | HF pinned, then the Bento GitHub Releases mirror (D3) | HF pinned |

Both SHA-256 values were re-checked against downloaded files on 2026-11-26.

## Embedding spaces

- Space id: `<model_id>@<revision>/<dims>`, from `space_id_for()`. Legacy vectors use `legacy:<provider>/<dims>` (`legacy_space_id()`). `parse_space_id()` rejects anything else.
- Every stored vector, chunk row and synced `asset_index.embedding` op carries `space`. Search queries only the active space.
- Peer vectors: `peer_vector_decision(active, peer_space, dims)` returns `index` only for the same space id and matching dims. Everything else, including old peers without `space`, is `store_only`.
- Matryoshka: the provider truncates to `space.dims` and re-normalises with `truncate_and_renormalize()` (an L2 norm of 1; non-finite or zero vectors are rejected). Vectors are compared with a dot product.
- An asset's vector score is the best of its chunks (`best_chunk_scores()`).

## Chunking

- `chunk_pages(pages)` / `chunk_text(text)` pack sentences into windows of at most `chunk_tokens` (512) **estimated** tokens. Long sentences split on words; words or unspaced CJK split on characters. Windows never span pages, and chunks are capped at 16 per asset, first pages first. Only the first `16 × 512 × 3 × 2` characters of a page are read.
- `estimate_tokens()` is conservative by design. Letters and whitespace count 3 characters per token; digits, CJK characters and punctuation count 1 token each; emoji count 3.
  - The spike checked it against the real `/tokenize`. On the 200-doc fixture, estimate ÷ real is ≥ 1.03 for EmbeddingGemma 2 and ≥ 0.93 for Qwen3. A "512" window measured at most 437 real EG2 tokens (459 Qwen3).
  - The earlier "4 characters per token" rule under-counted Spanish by up to 1.8×.
- Requests send `batched(chunks, 8)`, and every input stays below `ubatch_tokens`.

## Ports

| Port | Methods | Implemented by (Stage 24) |
|---|---|---|
| `ModelCatalogPort` | `default()`, `get(model_id, revision?)`, `all()` | `adapters/models/manifest_catalog.py` |
| `ModelDownloaderPort` | `download(file, dest_part, on_progress, should_stop) -> DownloadOutcome` (`completed \| stopped \| network \| failed \| checksum \| no_space`) | `adapters/models/http_downloader.py` |
| `ModelStorePort` | `installed()`, `path_for()`, `part_path_for()`, `free_bytes()`, `remove() -> bytes freed`, `verify()` | `adapters/models/filesystem_store.py` |
| `EmbeddingRuntimePort` | `ensure(spec, space, weights) -> EndpointInfo`, `stop()`, `health()`, `endpoint()` | `adapters/runtime/llama_server_process.py` |
| `EmbeddingProviderPort` (additive) | `space`, `embed_query(text)`, `embed_documents(texts, title=)`, `embed_image(path)` (raises `UnsupportedModalityError` on text-only spaces); the existing `is_enabled()`/`embed_asset()` stay | `adapters/embeddings/llama_cpp.py` |

`EndpointInfo` is what the worker writes to `<data_dir>/run/embedder.json` (mode 0600): `{space_id, base_url, api_key_file, pid, started_at}`. `base_url` is `http://127.0.0.1:<port>` or `http+unix://<socket>`. The key itself never appears in the file or in logs; only the 0600 key file path does.

Runtime flags, measured working at b12777:

```
llama-server -m <weights> --embeddings --pooling <pooling> -c 2048 -ub 2048 -b 2048 -np 1 \
  -t <threads> -tb <threads> --host <socket|127.0.0.1> --port <random> \
  --api-key-file <0600 file> --no-ui --offline
```

`--no-webui` still works as a deprecated alias. Threads default to `default_embedding_threads(cores) = min(4, max(1, cores // 2))`.

## Migration plan (`0009_smart_search`, Stage 24 vector-index-migration)

1. `asset_embeddings.space_id TEXT NOT NULL`, backfilled with `legacy:<provider>/<dimensions>`, plus an index on `(space_id, asset_id)`.
2. New `asset_embedding_chunks(space_id, asset_id, chunk_no, page, vector BLOB, created_at)`, with primary key `(space_id, asset_id, chunk_no)`.
3. New `embedding_spaces(id PK, model_id, revision, dims, modalities, state, created_at, activated_at)`, where `state` is one of `building | active | retired`. At most one row is `active`.
4. New `model_installs(model_id, revision, file, bytes_total, bytes_done, sha256, state, error_code, updated_at)`, with primary key `(model_id, revision, file)`.
5. New `smart_search_status` (single row): the persisted `SmartSearchStatus` fields.
6. Settings rows: `embeddings_provider` is rewritten with `migrate_embeddings_provider(value, custom_model_exists)` (`jina → custom` when the file exists, else `disabled`), and the `jina_model_path` key is renamed to `custom_model_path`.
7. `vec0` tables are not created by the migration. They are created at runtime per space as `asset_embedding_vec_<sha256(space_id)[:8]>`, because the dimension is part of the DDL.
8. Downgrade drops the new tables and the column, and restores the `jina` setting names. Legacy vectors are never deleted by the migration.

## Settings plan (Stage 24 vector-index-migration)

`GET /api/settings/schema` adds `platform` at the top level and, per field, `advanced` (`SettingDefinition.advanced`, shown under the group's "Avanzado" disclosure) and `hidden` (`is_hidden(key, platform)`). `constraints.choices` of `embeddings_provider` and `smart_search_model` are the platform's (`embeddings_provider_choices(platform)`, `smart_search_model_choices(platform)`), so Android lists neither `managed` nor any model. Validation uses the packaged manifest (`ModelCatalogPort`) for `smart_search_model` and `embedding_dimensions`.

- `embeddings_provider`: choices `disabled | managed | custom | mock` (`EMBEDDINGS_PROVIDER_CHOICES`), default `disabled`. The activation flow writes `managed`; the settings form never writes it directly.
- `smart_search_model`: a choice from the manifest, defaulting to `default_model_id`. Hidden while the manifest has a single recommended model for the platform.
- Advanced settings (group `ai`, `advanced=True`):
  - `custom_model_path`, keeping the `JINA_MODEL_PATH` and `BENTO_EMBEDDING_MODEL_PATH` env aliases;
  - `custom_mmproj_path`, `custom_query_prefix`, `custom_document_prefix`, `custom_pooling`;
  - `embedding_dimensions`, validated with `ModelSpec.validate_dims()` in `managed` mode;
  - `llama_server_path`, `embedding_server_url` (when set, Bento spawns no server), and `embedding_threads` (default as above).
- Onboarding (D8): the existing setup flow suggests smart search when `suggest_in_onboarding(cores, ram)` holds (≥ 4 cores and ≥ 8 GiB). The suggestion opens the same confirmation sheet; nothing is downloaded or enabled without the person pressing "Descargar y activar".
- Android (D6): `managed` is not offered. The setting stays `disabled`.

## Re-indexing (blue/green)

Activating a different space (a new model, revision or dims) creates an `embedding_spaces` row with `state = building` and queues `reembed` for this device's own assets. Search keeps using the `active` space until the new one reaches 100 %, or until the person chooses "Usar ya" (`POST /api/smart-search/use-now`). Then one transaction flips `active`, marks the old space `retired`, and drops its rows and `vec0` table. The old model files are deleted only after that.

For a model update the activation service does the glue: once the newer revision is verified it registers the space (`register_space`) and starts `reembed`, when its process has the space registry and re-embed owner wired. After the flip, `SmartSearchActivationService.space_activated()` (reached from `ReembedService` through `ActivationReembedObserver`) moves the status's `space_id` to the new space without changing its state, so the runtime supervisor serves the new model, and deletes the old revision's files and `model_installs` rows.

Progress is live. Each `reembed` scan remembers which of this device's assets still wait for their embedding job, and the worker reports every embedding job that ends for good (done, or failed on its last attempt) to `ReembedService.embedding_finished(asset_id)`. That moves `indexing.done` forward by one per asset (a retried attempt or a duplicate job never counts twice), and the last one runs the final check at once: the flip when needed, then `indexed` → `ready`. The `wait` check job, due 60 s later, stays as the fallback for work this process did not scan (for example after a worker restart); once live progress completed the space it is closed without running.

## Activation and removal while the processes run

Activation and removal take effect without restarting the API or the worker (they write `embeddings_provider` through the settings service, but nothing restarts the sidecars). Unless `embeddings_provider` is pinned elsewhere (`custom`, `mock`, `disabled` from the environment or a policy, or a platform without `managed`, see `follows_smart_search_status`):

- the worker always builds the runtime supervisor as `managed` and follows the persisted status every tick: `off` serves nothing (embedding jobs are no-ops), `starting`/`indexing`/`ready` start the server for the status's space, and removal stops it;
- the API re-reads `embeddings_provider` (one indexed SQLite read) and the status's `space_id` on each search and rebuilds its search wiring only when that pair changes; `GET /api/settings` folds the same live value;
- uploads queue embedding jobs from the live value too.
