# Smart search: model download under real network failures (Linux, 2026-11-27)

**Verdict: PASS after one fix.** The download survived connection resets, a 3-minute stall, a 3-minute outage, an outage longer than the retry budget, a truncated body, a corrupted body and a DNS failure. Every resume sent `Range` from the exact byte where the previous connection stopped. No resume restarted at zero, and the product never marked a bad file ready. The fix: before it, the job's in-job retry waits were never reset, so drops spread over a long download used them up even though bytes kept arriving between them (bug 1, fixed here). An unrelated bug found on the way leaves the status stuck at `indexing` after a quick remove and re-activate (bug 2, documented, not fixed: it is outside the download code).

This closes the "pull the network cable mid-way, it resumes" step of the Stage 25 exit (`execution/smart-search-program.md`). Earlier passes only covered pause/resume and a worker SIGKILL (`smart-search-real-model-2026-11-26.md`, `smart-search-real-model-pass-2-2026-11-27.md`).

## Method

- **Real download path.** The worker downloaded the pinned file from Hugging Face (`ggml-org/embeddinggemma-2-GGUF@6ea3e3a3…`, `embeddinggemma-2-Q8_0.gguf`, 309,855,456 B, then the 302 redirect to `us.aws.cdn.hf.co`). `HttpModelDownloader` uses `urllib.request.build_opener`, whose default `ProxyHandler` reads `HTTPS_PROXY`. So the worker ran with `HTTPS_PROXY=http://127.0.0.1:18891`, and no test seam or code change was needed. The machine's network was never touched: no `nmcli`, `ip link`, `iptables` or `sudo`.
- **Fault proxy.** A throwaway asyncio HTTPS `CONNECT` proxy (about 300 lines, deleted after the pass), driven over a localhost control port, had these modes:
  - `reset`: TCP RST on every open tunnel (`SO_LINGER` 0).
  - `stall`: tunnels stay open but move no bytes, and new `CONNECT`s are read and never answered.
  - `refuse`: the listener is closed (`ECONNREFUSED`) and open tunnels are reset.
  - `dns`: the proxy resolves `<host>.invalid` (a real `getaddrinfo` failure) and answers `502`.
  - MITM: TLS is terminated with a local CA, so the proxy can corrupt one byte or end the TLS stream cleanly at an absolute file offset. The worker trusted the CA through `SSL_CERT_FILE` (the system bundle plus the test CA). The proxy logged the `Content-Range` start of every `206`, which shows each resume offset exactly.
- **Product.** Throwaway `DATA_DIR=~/.cache/bento-netfault/data` with `BENTO_RUNTIME_MODE=headless`, `HOST=127.0.0.1`, `API_PORT=18754`, `STORAGE_BACKEND=local`, `OCR_PROVIDER=disabled` and `WORKER_CONCURRENCY=1`. There was no Telegram and no `.env`. The processes were `python -m bento.interfaces.desktop.launcher {migrate,api,worker}`, plus the pinned `llama-server` b12777 copied from an earlier pass. Activation, retry and removal went through the API.
- **Sampling.** A poller read `GET /api/smart-search`, the `.part` size and the `model_download` job row (status, attempts, `run_after`) every 0.5 s: 3,713 samples. A driver script fired each fault when `bytes_done` crossed its threshold.
- **Code.** Runs A and B ran on `main` at `c40504f4`. Run C ran on `c40504f4` plus the bug 1 fix from this PR. About 1.24 GB was downloaded in total, at 1.6-2.0 MB/s.

The user-facing text comes from the web's `describeSmartSearch` (`apps/web/src/features/settings/smart-search/model.ts`) and the Spanish dictionary:

| State | Text | Action |
|---|---|---|
| `downloading` | «Descargando… {done} de {total}» | Pausar |
| `downloading` + `waiting_network` | «Esperando conexión · se reanudará sola» | Pausar |
| `error(download)` | «No se pudo descargar el modelo.» | Reintentar |
| `error(checksum)` | «El archivo descargado no es correcto y se borró.» | Reintentar |

The progress bar keeps its value while the status is `waiting_network`.

## Results

"Detect" is the time from the fault to the first `waiting_network: true` sample, or to the error state. "Resume" is the time from the network coming back to bytes flowing again.

| # | Scenario | Bytes at fault → resumed from | Same byte | Detect | Retries / backoff seen | Resume | Final state | What the user sees |
|---|---|---|---|---|---|---|---|---|
| 1a | RST at 30 % (run A) | 94,961,664 → 94,961,664 | yes | < 0.2 s (`ConnectionResetError`) | 1 in-job wait of 1 s | 2.2 s | `ready` (run A) | «Esperando conexión…» for 2 s, then «Descargando…» |
| 1b | RST at 70 % (run A, before the fix) | 218,497,024 → 218,497,024 | yes | < 0.2 s | **32 s** in-job wait: the waits were used up by 1a and 2 (bug 1). One more drop would have sent the job back to the queue | 33 s | `ready` | «Esperando conexión…» for 33 s on a working network |
| 1c | 9 RSTs, one every 10 % (run C, after the fix) | each at 31.9, 63.0, 93.6, 124.6, 156.0, 186.1, 217.6, 248.9 and 279.8 MB → the same byte (proxy `Content-Range` = worker's "interrupted at") | yes, 9/9 | < 0.5 s each | a 1 s wait each time; the same job run throughout (`attempts` stayed 1) | 2.0-2.5 s each | `error(checksum)` from 5b, then `ready` | 9 blips of «Esperando conexión…» |
| 2 | Stall 3 min at 45 %: connection open, no bytes (run A) | 139,853,824 → 139,853,824 | yes | **30.2 s** (read timeout, `TimeoutError`) | each attempt: 30 s timeout on HF + 30 s on the mirror, waits of 2, 4, 8, 16 s between them | 17.7 s after the stall ended (it was in the 16 s wait) | `ready` | «Esperando conexión · se reanudará sola» from 30 s after the stall began, then «Descargando…» |
| 3 | Outage 3 min at 35 %: connections refused (run B) | 109,576,192 → 109,576,192 | yes | < 0.3 s | in-job waits 1-32 s (63 s), queue retry +60 s (attempt 2), in-job again | 7.7 s after the outage ended | continued into 4 | «Esperando conexión…» for 3 min 8 s, the bar held at 35 % |
| 4 | Outage longer than the retry budget at 60 % (run B) | 186,253,312 → after `retry`, 186,253,312 | yes (MITM log: `206` from 186,253,312) | `error(download)` 63 s after the final attempt began | the job went straight back to the queue with no in-job waits (bug 1). Then the budget was fast-forwarded (see below) | no automatic resume. `POST /retry` 30 s after the network came back resumed in 1 s | `error(download)` → `retry` → `downloading` | «No se pudo descargar el modelo.» + «Reintentar». The status stayed `error` while the network was back, until retry |
| 5a | Truncated body: TLS closed cleanly at 247,884,364 (80 %) although `Content-Length` promised more (run B, MITM) | 247,884,364 → 247,884,364 | yes | 0.4 s | 1 s wait | 2.3 s | reached `starting`/`indexing` with the correct hash. Then bug 2 | a 2 s blip |
| 5b | Corrupt body: one byte flipped at 170,420,500 (run C, MITM) | the whole file arrived (309,855,456 B) | n/a | at the end of the download, 90 s after the corruption (the hash is streamed and compared when the last byte lands) | none. The `.part` was deleted | `retry` restarted from 0 (the documented checksum behaviour) and completed in 2 min 50 s | `error(checksum)`, `failed_step: verifying` → `retry` → `ready` | «El archivo descargado no es correcto y se borró.» + «Reintentar». Never `ready` with the bad file |
| 6a | DNS failure at activation, proxy hop: `getaddrinfo` failed for the origin, `502` (run B) | 0 → 0 | n/a | 0.6 s | in-job waits (63 s), then the queue (+30 s) | 4.6 s after DNS came back (90 s outage) | continued into 3 | «Esperando conexión…» from the first second |
| 6b | DNS failure at activation in the worker: `HTTPS_PROXY=http://bento-netfault-proxy.invalid:18891` → `URLError(gaierror(-2))` (run C) | 0 → 0 | n/a | 0.9 s | in-job waits (63 s), then the queue (+30 s) | the worker was restarted with a resolvable proxy (the env cannot change in a running process); the requeued job ran at its `run_after`, and bytes came 18 s after the restart | continued into 1c | «Esperando conexión…» |

Notes on the runs:

- **Run A timeline**: activate t+0, RST t+49 s, stall t+74 s to t+254 s, RST t+310 s, `starting` at t+389.6 s, `ready` at t+390.6 s.
- **Run B timeline**: activate t+0, DNS back t+90 s, outage t+156 s to t+336 s, long outage from t+396 s, `error` at t+460 s, retry at t+510 s, truncation at t+555 s, `starting` at t+595 s.
- **Run C timeline**: activate t+0, worker restarted t+78 s, 9 RSTs between t+113 s and t+275 s, `error(checksum)` at t+294 s, retry at t+304 s, `ready` at t+476 s.
- **Bytes**: `bytes_done` never decreased while `downloading` in any run, and the `.part` never shrank, except when the checksum error deleted it on purpose (5b). Every completed file passed the product's SHA-256 check.
- **Budget fast-forward (4)**: the real budget is 8 job attempts, each with 63 s of in-job waits, and queue backoff of 30 s × 2ⁿ between them (30, 60 … 1,920 s): about 72 min of continuous outage. While the job sat in the queue, the driver set its `attempts` to `max_attempts - 1` and its `run_after` to now in SQLite, so the next run was the last one. Everything after that point is the product's own behaviour.
- **The mirror URL answers 404.** The manifest's fallback URL (`github.com/invrnt/bento/releases/download/models-embeddinggemma-2-6ea3e3a3/…`) answered `HTTP 404` whenever it was reachable, so there is no working fallback today if Hugging Face is down. During a stall, each attempt also spends a second 30 s timeout on that URL. The fallback is an open `bento-release` task (§Distribution), not a downloader bug.

## Bugs found

### 1. Drops with progress in between used up the in-job retry waits (fixed in this PR)

`SmartSearchActivationService._download_with_retries` ran `for attempt in range(len(delays) + 1)` over `NETWORK_RETRY_DELAYS = (1, 2, 4, 8, 16, 32)` and never reset `attempt`. An attempt that downloaded 100 MB and then dropped counted the same as one that could not connect.

What it caused in run A and run B:
- After two earlier drops, the RST at 70 % (1b) waited 32 s on a working network.
- The outage at 60 % (4) found no in-job waits left and sent the job straight back to the queue. That used up a queue attempt (8 in all) and a backoff of 30 s × 2ⁿ.

On a flaky link (a hotspot or bad Wi-Fi) that drops every few tens of megabytes, every seventh drop cost a queue attempt. After about 55 drops the download ended in `error(download)` although it was making progress.

Fix: `attempt` returns to 0 whenever an attempt received bytes (`outcome.bytes_done > start`), so only an outage with no progress uses up the waits. The loop still ends: bytes are bounded by the file size, and a restart from zero cannot reset `attempt` because `start` keeps the high mark. Run C (1c) showed the fix in the product: 9 drops in one job run, each resumed after a 1 s wait.

Tests (fakes plus loopback sockets, no internet):
- `test_drops_with_progress_in_between_do_not_use_up_the_in_job_waits`: one in-job wait and four separate RST drops; the job completes. It fails on `main` with `ModelDownloadRetryLater`.
- `test_an_outage_with_no_progress_still_ends_the_in_job_waits`: the waits still run out when no bytes arrive.

### 2. Removing and re-activating within 30 s leaves the status at `indexing` forever (not fixed: `interfaces/worker/smart_search.py`, embeddings-runtime)

In run B, activation came 2 s after `DELETE /api/smart-search/model`, in the same worker process that had served the space in run A. `SmartSearchSpaceJanitor` retires spaces only when it sees `off`, and it sweeps every 30 s, so the space was still `active`. `RuntimeStatusRelay._prepare_space` then took the not-fresh branch, found `space_id in self._started` and returned. No `reembed` was queued, nothing called `indexed`, and the status stayed `indexing 0/0` («Revisando tus archivos…») for more than 2.5 min, until the worker was restarted.

Suggested fix: in `_prepare_space`, check "status is `indexing` for this space and no `reembed` is waiting" before the `_started` early return. The job is idempotent. Another option is to clear `_started` for a space when the status goes through `off`. Neither the program's journey test nor pass 2 caught this, because both waited for the janitor before activating again.

## Not changed, worth knowing

- **Resume lag after a long outage.** Once the in-job waits (63 s) run out, the job waits in the queue until its `run_after`. The status keeps saying «se reanudará sola», which stays true. The lag after the network returns was 4.6 s and 7.7 s here, but it grows with the outage: up to 8 min when the network returns 13-21 min into the outage, and up to 32 min near the end of the 72 min budget. The UI has no "try now" action while `waiting_network`; after the last attempt, «Reintentar» resumes at once. If that matters, the cheapest change is a lower queue base delay for `model_download`, or a "Reintentar ahora" action while waiting. No code change was made here, because it is a product decision.
- **Detection time for a corrupt body** is the length of the download. The streamed hash is checked when the last byte lands, then the `.part` is deleted and `retry` starts from zero. A per-block hash list would allow a partial re-download, but Hugging Face publishes only the file's SHA-256, so the manifest has nothing to pin per block.
- **A stall costs 30 s per URL tried.** Lowering the 30 s timeout would detect a stall sooner, but it would cut slow links during TLS setup or the CDN's first byte. 30 s is kept.

## Also in this PR

- `HttpModelDownloader` logs "Model download ended early at N bytes" when a body ends before its `Content-Length`. That case was the only silent one. Its docstring now states the read timeout and the proxy support.
- Adapter tests over loopback sockets: a TCP RST mid-body keeps the bytes and the next call resumes with `Range` at that byte; a silent connection ends at the read timeout (0.5 s in the test) instead of hanging, and the next call resumes; a body that ends before its `Content-Length` is resumed, not accepted.
- `tests/fakes/model_host.py` gains `next_drops` (a flaky link), `reset` (RST instead of FIN), `stall_at`/`stall_seconds` and `short_body_at`. With `drop_once=False`, a request that starts at or past the drop offset is cut too (no test used `drop_once=False` before).
- `execution/smart-search-program.md` §Ports: one bullet with the measured retry policy.

Backend: `scripts/local-ci.sh --backend` on the PR head (see `local-ci.md`).

## Cleanup

The API, worker, `llama-server`, poller, driver and proxy were stopped. The model was removed through the API, then the throwaway data dir (`~/.cache/bento-netfault`), the proxy, its CA and leaf certificates, the CA bundle, the copied `llama-server` and the run logs (`/tmp/bento-netfault`) were deleted.
