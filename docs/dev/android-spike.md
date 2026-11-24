# Android engine spike (Stage 19, agent 34)

Question: can the unchanged `apps/api/src/bento` package run embedded in an Android APK through Chaquopy within
the budgets of `orchestration/product/android.md` §13? Gate: `orchestration/architecture/android-runtime.md` §12.

Project: `spikes/android-engine/` (throwaway; deleted when Stage 20 merges). One Activity with a button per action
and a log view; every action can also be driven with `am start --es action <name>` (`tools/act.sh`). The backend
source set is `apps/api/src` itself, not a copy. Every Android-specific change lives in
`app/src/main/python/bento_spike/patches.py` as a monkeypatch and is listed under
[Required backend changes](#required-backend-changes-for-agent-35).

> **Paths after Stage 20.** `spikes/android-engine/` was deleted when Stage 20 merged; this report is kept as the
> historical record and its paths refer to that removed project (see git history before `feature/android` commit
> "Merge Stage 20 Android platform"). Current homes: wheels → `apps/android/python-wheels/` (`build_all.sh`,
> `build_rust_wheel.sh`, `fix_ext_suffix.py`; requirements generated from the backend's `android` extra by
> `generate_requirements.py`); the monkeypatches in `bento_spike/patches.py` became real backend code
> (`bento.interfaces.android.engine`, `bento.adapters.android.*`, `bento.infrastructure.db.migrate`); the
> engine/app is `apps/android/` (`apps/android/README.md`). compileSdk moved to 37 (minor 2) at Stage 20 for the
> Compose BOM 2026.11.01; targetSdk stays 36. The Reproduce section below no longer runs as written: use
> `apps/android/README.md`.

**Measurement environment.** No physical device was available. Every number below comes from an
**emulator**: AVD `bento_spike_api35` (Pixel 7 profile, Android 15 / API 35, `google_apis` x86_64 image, 4 vCPU,
3 GB RAM, KVM) on an AMD Ryzen 7 5800H host. x86_64 numbers run natively on a fast desktop CPU, so they are
optimistic compared with a phone. arm64 builds ran on the same image through `libndk_translation` (ARM→x86
binary translation). That proves the arm64 wheels load and work, but the arm64 timings are translation
overhead, not phone performance. None of these numbers stands in for the floor or reference device.

## Verdict

| §12 item | Result | Key evidence |
|---|---|---|
| 1. Imports + `alembic upgrade head` on arm64 and x86_64, FTS5 | **Go** | Both ABIs: migrations reach `0006_sync_trust`; SQLite 3.53.4 with `ENABLE_FTS5`; app table `asset_fts` created; `EXT_SUFFIX` `.cpython-313-aarch64-linux-android.so` on the arm64 build |
| 2. `/api/health` from OkHttp with token guard; `thumbnail` job via `MediaTools` | **Go** | 200 with bearer, 401 `api_token_required` without; thumbnail job `succeeded` in < 1 s, 3 bridge calls (ImageDecoder), `/thumbnail` returns JPEG |
| 3. Telethon: fake cloud + real account, QR + phone login, 200 MB v2 up/down with resume after kill | **Go on the fake cloud. Real Telegram pending owner** | Fake: QR and phone login, vault created, 200 MB upload + download with matching SHA-256, SIGKILL after 2 of 4 parts, then resume uploads only parts 3–4. Real-account steps below |
| 4. Relay pairing as guest (login-token forwarding) + 5,000-asset bootstrap | **Go with a deviation** (host is a second Android process, not a desktop) | Relay transport, SAS match, host approves, guest signed in by the forwarded token, same vault; 5,000 assets on the guest 23.4 s after the code was typed; see [Pairing](#4-relay-pairing) |
| 5. Measurements | **Partial: emulator only**. Python PSS misses the budget | Engine ready p90 3.06 s (x86_64 emulator); Python PSS ≈ 152 MB (budget 120, **+27 %**); arm64 APK 29.1 MB per-ABI download (35.9 MB from the AAB); throughput far above 8 MB/s on the fake cloud; real-Wi-Fi throughput and battery pending owner |
| 6. `tg://login?token=` on the same phone | **Pending owner** (no Telegram app or account on the emulator) | The backend's QR URL scheme is `tg://`. Steps below |

**Recommendation: Go for Stage 20 (Plan A).** Items 1–4 pass with the backend source unchanged. Five small
monkeypatches plus wheel and packaging work are enough (list below). No result is a 1–4 miss. Python PSS is the
only budget miss, at +27 %, below the 50 % Plan B trigger, and it has clear cuts (see
[Memory](#memory-pss)). Before release the owner should confirm three things on real hardware: engine ready on
the floor device, which is the largest unknown since the x86_64 emulator leaves ~25 % headroom under the 4 s p90;
Python PSS after the cuts; and real-Telegram throughput with `cryptg`.

## Versions pinned

| Component | Version | Notes |
|---|---|---|
| Android Gradle Plugin | 9.5.2 | latest stable; built-in Kotlin |
| Kotlin Gradle Plugin | 2.4.21 | pinned through `buildscript` classpath (AGP 9.5.2 would default to KGP 2.2.10) |
| Gradle | 9.9.2 | AGP 9.5 does not run on 9.3.1 (`NoClassDefFoundError: org/gradle/features/binding/ProjectTypeBinding`) |
| Chaquopy | 17.2.0 | supports AGP 7.3–9.5, Python 3.10–3.15, minSdk 24 |
| Python | **3.13** (target `3.13.16-0`) | see below |
| JDK | Temurin 17 | JDK 27 is too new for AGP |
| NDK (wheel builds) | r27b (27.1.12297006) | `aarch64/x86_64-linux-android24-clang` |
| Rust / maturin | 1.95.0 / 1.16.0 | PyO3 0.28 (pydantic-core), 0.30 (cryptg) |
| compileSdk / targetSdk / minSdk | 36 / 36 / 29 | minSdk = the floor device (Android 10) |
| OkHttp | 4.12.0 | spike only |

Python choice: §4 asks for the newest Chaquopy-supported version that satisfies `>= 3.12`. Chaquopy 17.2 offers
3.14 and 3.15, but its package repository has `cryptography`, `pillow`, `cffi`, and `greenlet` Android wheels
only up to **cp313**. PyPI has no Android wheels for any of them. With 3.14 we would have to cross-build four more
native packages, including cryptography's Rust + OpenSSL stack. 3.13 is the newest version where only
`pydantic-core` and `cryptg` need local builds. Revisit when the Chaquopy repository publishes cp314 wheels.

Resolved Python packages (Chaquopy pip, `requirements-android.txt`): fastapi 0.115.14, starlette 0.46.2,
pydantic 2.13.4, pydantic-core 2.46.4, pydantic-settings 2.16.3, sqlalchemy 2.0.58, alembic 1.20.1, mako 1.4.3,
cryptography **42.0.8**, cffi 1.17.1, spake2 0.9, hkdf 0.0.3, segno 1.6.6, telethon **1.46.0** (uv.lock has
1.45.0), pyaes 1.6.1, rsa 4.9.1, uvicorn 0.34.3 (no `[standard]`), h11 0.16.0, click 8.5.1, websockets 17.4,
python-multipart 0.0.34, pillow 11.0.0, greenlet 3.1.1, markupsafe 3.0.4, anyio 4.16.0, cryptg 0.6.1.
Stage 20 must pin these from `uv.lock`; the spike resolved ranges.

## Wheels

Chaquopy 17 installs with `--only-binary` and does not build sdists from an index. Sources:

| Package | Source | Detail |
|---|---|---|
| `pydantic-core` 2.46.4 | **Built locally** | Neither PyPI nor the Chaquopy repo has Android wheels. `wheels/build_rust_wheel.sh`: maturin cross-build against the exact Chaquopy target `libpython3.13.so` (PyO3 config file, `shared=true`), NDK clang as linker; ~75 s per ABI. maturin names the extension `*.cpython-313-<arch>-android-android.so`, so `fix_ext_suffix.py` renames it to the interpreter's `EXT_SUFFIX` and rewrites `RECORD`. Without that rename `import pydantic_core._pydantic_core` would fail. |
| `cryptg` 0.6.1 | **Built locally** | Same script (PyO3 0.30), ~5 s per ABI. The wheel metadata says `0.1.0` (taken from `Cargo.toml`); harmless, but fix it in CI. |
| `cryptography` 42.0.8 | Chaquopy repo | Newest Android build there; the backend pins `>=46,<47` (deviation, see changes). OpenSSL 3.5.9 from Chaquopy. |
| `cffi` 1.17.1 | Chaquopy repo | dependency of cryptography 42 |
| `pillow` 11.0.0 | Chaquopy repo | pulls `chaquopy-libjpeg`, `chaquopy-freetype` |
| `greenlet` 3.1.1 | Chaquopy repo | pulled by SQLAlchemy's `platform_machine` marker |
| `markupsafe` 3.0.4 | PyPI (official `android_24_*` wheel) | the only native dependency with Android wheels on PyPI |
| `pyaes` 1.6.1, `hkdf` 0.0.3 | **Built locally** (pure, `pip wheel`) | sdist-only on PyPI; Telethon and spake2 need them |
| everything else | PyPI `py3-none-any` | |

`wheels/build_all.sh` rebuilds all locally built wheels into `wheels/dist/` (git-ignored), which Gradle passes as
`--find-links`. The cibuildwheel path was not needed: maturin with a PyO3 config file was simpler and
reproducible. Stage 20 should run the same script in CI and publish to the internal index.

## 1. Imports, migrations, FTS5

- `bento.interfaces.http.main`, `bento.interfaces.worker.main`, uvicorn, and alembic import on both ABIs once
  the watchdog stub is installed (patch 1).
- `alembic upgrade head` runs from `alembic.ini` + `migrations/`, which Gradle copies into an extracted
  `bento_migrations` package (`extractPackages`). Alembic needs real files. First run: 0001→0006 in 402 ms
  (x86_64). Each cold start already at head: 11–14 ms.
- `sqlite3`: SQLite 3.53.4 with `ENABLE_FTS5`, `THREADSAFE=1`. `CREATE VIRTUAL TABLE … USING fts5` works, and
  the app's `asset_fts` table exists after migration. FTS5 is enabled since Chaquopy 17.1.
- arm64 build: `ext_suffix .cpython-313-aarch64-linux-android.so`, `_pydantic_core.cpython-313-aarch64-linux-android.so`
  loaded, OpenSSL 3.5.9. `platform.machine()` reports `x86_64` there because it is the host kernel's value
  under translation.

## 2. API, token guard, worker, MediaTools

- Kotlin generates a 32-byte token per process, base64url. Python receives it in memory:
  `process_secrets.adopt_environment_secrets` is called with a private mapping, so the token never enters
  `os.environ`. The device wrapping key travels the same way.
- The API runs on a uvicorn thread bound through the backend's `bind_loopback_listener` (ephemeral
  `127.0.0.1` port). The worker runs `run_worker()` on its own thread and asyncio loop. Same process, separate
  loops, as §2 requires. uvicorn skips signal handlers off the main thread, so nothing needed changing.
- OkHttp `GET /api/health`: 200 with `Authorization: Bearer …`, 401 `api_token_required` without. First
  health call takes 43–68 ms after the API reports started.
- Kotlin uploads a 4000×3000 JPEG (multipart, OkHttp). The worker's `thumbnail` job succeeds in 0.56–0.95 s;
  the `MediaTools.thumbnail` bridge (ImageDecoder with target size, JPEG q85) is called 3× (256, 512, 1600 px).
  `GET /assets/{id}/thumbnail` returns 200 `image/jpeg`. The bridge is called through `java.jclass` from the
  patched generator (patch 3).

## 3. Telegram: fake cloud

Run with `STORAGE_BACKEND=fake` and `BENTO_TELEGRAM_PART_SIZE_MB=64`. The 64 MB part size is the minimum and
gives a 200 MB file 4 parts, which makes resume observable.

| Step | x86_64 (emulator) | arm64 (translated) |
|---|---|---|
| QR login (fake auto-approve) → `authorized`; `qr_url` scheme `tg` | 2.1 s | 2.4 s |
| Phone login (`/login/phone` → `code_required` → `/login/code` → `authorized`) | 21 ms | not run |
| Vault create + recovery-code confirm → `ready` | ok | ok |
| 200 MB HTTP ingest (`POST /assets/upload`, loopback, streamed multipart) | 2.4 s (82.7 MB/s) | 8.6 s |
| `remote_upload` (v2 encrypt + 4 parts to the fake cloud), upload session first→last write | **3.3 s (≈ 60 MB/s)**; job wall 4.7 s | 9.8 s (≈ 20 MB/s) |
| 200 MB download + decrypt through the remote store, SHA-256 match | **3.05–3.3 s (60–66 MB/s)**, match | 8.6 s (23 MB/s), match |
| SIGKILL after 2 of 4 parts committed, cold restart | parts 1–2 (`message_id` 13, 14) kept; only parts 3–4 (15, 16) uploaded; job `succeeded`; download digest matches | not run |

The kill is a real `SIGKILL` from inside the process (`upload_then_kill`), fired as soon as `upload_sessions`
has 2 durable parts. On restart the worker's `release_abandoned` requeues the job. `parts_reuploaded` is empty.

Observation for Stage 20, not a gate item: `TelegramVaultBlobStore` writes the full ciphertext to a temp file
plus one part copy. Peak temp disk is therefore about file size + part size, and a resume re-encrypts the whole
file before it uploads the missing parts. On a phone, a 4 GB video needs about 4.5 GB free. Consider per-part
streaming encryption, which the v2 format already permits (segments are independent), or check free space
before upload.

### Crypto ceilings (`aes_bench`)

| | x86_64 | arm64 (translated) |
|---|---|---|
| AES-256-GCM (cryptography 42 / OpenSSL 3.5), 1 MB chunks | 73–133 MB/s | 46 MB/s |
| SHA-256 (hashlib) | 294–325 MB/s | 62 MB/s |
| Telethon AES-IGE with `cryptg` | 293–432 MB/s | 8.1 MB/s |
| Telethon AES-IGE without `cryptg` → **pyaes** (pure Python) | **0.38–0.40 MB/s** | 0.08 MB/s |
| Telethon AES-IGE via its `libssl` fallback, patched to find `libssl_python.so` | 5.3 MB/s | 1.3 MB/s |

Without `cryptg`, Telethon on Android has no working native fallback. Its ctypes `libssl` lookup searches for
`ssl`, but Chaquopy ships OpenSSL as `libssl_python.so` and `libcrypto_python.so`. It therefore drops to pyaes
at about 0.4 MB/s, which is about 20× below the 8 MB/s budget even on a desktop CPU. **`cryptg` is mandatory in
the `android` profile.** The arm64 figures are translation artifacts: `cryptg`'s Rust AES is much slower under
`libndk_translation`. Real arm64 phones have ARMv8 AES instructions. Measuring real throughput needs a device
and a real account.

## 4. Relay pairing

Constraint: phone and host must share one fake cloud, and the fake cloud is a directory. The remote fake cloud
(`fake-telegram-serve`) is an agent 35 deliverable. The spike therefore runs the **host as a second interpreter in a
separate Android process** (`HostService`, `android:process=":host"`, own data directory). It shares the fake
cloud directory with the guest in the main process. The relay is the backend's Python relay double
(`apps/api/tests/integration/pairing/relay_double.py`, which mirrors `apps/relay`) running on the Linux host,
exposed to the phone with `adb reverse tcp:P tcp:P`. Both engines use `BENTO_RELAY_URL=ws://127.0.0.1:P`.

Flow (`pair_guest`): host `POST /pairing/host` (transport `relay`, `bento://join` link) → guest `POST /pairing/join`
with the code → both reach `awaiting_approval` with the same 4-emoji SAS → host approves → both `completed`.
The guest was signed out with manual login, so only the host's forwarded login token can sign it in. It ends
`authorized` and its vault is `ready` with the host's `vault_id`.

| Run | Pairing (code → both completed) | Bootstrap | Result |
|---|---|---|---|
| 200 assets | 0.57 s | 200/200 in 2 s | pass |
| 5,000 assets | 0.57 s | 5,000/5,000 present by the time the guest vault reported `ready` (code typed → full library: 23.4 s) | pass |

Seeding the 5,000-asset host took 2,035 s through its HTTP API (5,000 sequential `POST /assets/upload` +
`remote_upload` jobs). The first 200 uploads ran at ~23 assets/s, the last ones at ~1.7 assets/s. Two
explanations remain open. During that run the `:host` process was unbound, so Android may have placed it in a
background CPU group (see the freezer finding below). Or per-upload cost may grow with library size. Agent 35
should reproduce the 5,000-file seed on desktop to tell them apart before the phone's initial backup
(thousands of photos) depends on it.

Finding (Android lifecycle): the first 5,000-asset pairing attempt timed out because the `:host` process,
started but unbound, had been **frozen by the cached-app freezer** (`isFrozen=true`, procState 10, 0 % CPU).
Its loopback API stopped answering mid-request. Binding the service with `BIND_IMPORTANT` fixed it. This
confirms `android-runtime.md` §3/§6: the engine must only run while a holder keeps the process in a
non-cached state (visible UI, a bound/foreground service, WorkManager, or UIDT). Any engine work outside a
holder simply freezes.

Deviation: the guest path (the one that matters for the phone) runs entirely on Android, and so does the host
path. A real desktop host on another machine was not exercised. That needs the remote fake cloud
(Stage 20, agent 35) or a real account. Finding: the host reports the Android guest's platform as `other`
(change 7).

## 5. Measurements (emulator)

### Engine ready: 20 cold starts, x86_64 (`tools/cold_starts.sh`)

`am force-stop`, then launch with `action=ready`. Measured from `Process.getStartUptimeMillis()` to the first
successful OkHttp `/api/health`. Database already at head.

| Metric | p50 | p90 | min | max |
|---|---|---|---|---|
| **Engine ready (API answering)** | **2,888 ms** | **3,060 ms** | 2,777 | 5,548 (run 1) |
| Interpreter ready (warm-up imports done) | 2,708 | 2,882 | 2,586 | 5,360 |
| `Python.start` | 418 | 450 | 379 | 874 |
| Warm-up imports (fixed order) | 2,208 | 2,364 | 2,101 | 4,238 |
| Migrations (fast path at head) | 12 | 14 | 11 | 14 |
| API start (listener + uvicorn) | 114 | 120 | 109 | 124 |
| First frame (`am start -W` TotalTime, spike Activity) | 720 | 790 | 661 | 2,102 |

Budget: ≤ 2.5 s p50, ≤ 4 s p90 **on the floor device**. The x86_64 emulator is a fast desktop core, so it
misses the p50 already (2.89 s against 2.5 s) and passes p90 with ~25 % headroom. A 4 GB Android 10 phone will
be slower. The import work below is required to meet the budget. Separately, the first run after install pays a
one-time asset extraction (6.06 s). The arm64-translated first start was 10.7 s, which is not representative.

### Import-time profile (top 20, CPython `-X importtime`, x86_64 emulator)

Captured by setting `PYTHONPROFILEIMPORTTIME=1` and `dup2`-ing fd 2 to a file before `Python.start`
(`files/import-time` marker). 1,357 modules, 2,516 ms total self time.
Raw: `spikes/android-engine/results/raw/importtime_x86_64.txt` (cold starts, memory, bundletool and pairing raw results sit next to it).

| # | Module (cumulative) | self ms | cumulative ms |
|---|---|---|---|
| 1 | `sqlalchemy.orm` | 1.0 | 520.0 |
| 2 | `bento.interfaces.http.main` | 62.0 | 465.1 |
| 3 | `sqlalchemy` | 4.0 | 414.4 |
| 4 | `bento.interfaces.http.routes` | 77.3 | 343.2 |
| 5 | `bento.interfaces.desktop.launcher` | 0.5 | 342.4 |
| 6 | `fastapi` | 0.4 | 320.2 |
| 7 | `fastapi.applications` | 2.4 | 319.1 |
| 8 | `fastapi.routing` | 3.3 | 307.9 |
| 9 | `sqlalchemy.engine` | 0.8 | 294.6 |
| 10 | `telethon` | 0.6 | 272.7 |
| 11 | `sqlalchemy.engine.events` | 3.4 | 271.3 |
| 12 | `telethon.client.telegramclient` | 0.0 | 270.9 |
| 13 | `telethon.client` | 0.3 | 270.9 |
| 14 | `sqlalchemy.engine.base` | 6.1 | 267.9 |
| 15 | `fastapi.params` | 1.5 | 265.0 |
| 16 | `fastapi.openapi.models` | 124.3 | 263.5 |
| 17 | `sqlalchemy.engine.interfaces` | 6.8 | 260.9 |
| 18 | `telethon.client.telegrambaseclient` | 1.0 | 230.4 |
| 19 | `sqlalchemy.sql.compiler` | 0.0 | 228.6 |
| 20 | `sqlalchemy.sql` | 18.8 | 228.6 |

Largest self times: `fastapi.openapi.models` 124 ms, `telethon.tl.types` 90 ms, `bento.interfaces.http.routes`
77 ms, `bento.interfaces.http.main` 62 ms, `bento.infrastructure.db.models` 61 ms, `urllib.request` 60 ms.
By package (self): bento 587 ms (23 %), sqlalchemy 500 (20 %), telethon 224 (9 %), fastapi 160 (6 %), alembic 70,
urllib 64, pydantic 63, java (Chaquopy) 61.

Suggestions to cut cold start, in expected order of payoff:

1. **Do not import `interfaces.desktop.launcher` on Android** (342 ms cumulative). It drags in alembic, the
   argparse CLI, and process helpers just to reach `bind_loopback_listener` and `_run_migrations`. Move both into a
   small module, and check `alembic_version` with plain `sqlite3` so alembic is imported only when a migration is
   actually pending.
2. **Start the API before the worker's heavy imports.** The worker (Telethon 273 ms, sync engine) can import on
   its thread while uvicorn already answers. Engine ready then waits only for `http.main` and its routes.
3. **Lazy Telethon** (273 ms): import it on the first MTProto use. In debug/fake builds it is not needed at all.
4. **Avoid building FastAPI's OpenAPI models at startup** (`fastapi.openapi.models` 124 ms self).
   Pre-generated schema plus `openapi_url=None` in release builds; OpenAPI is consumed at build time
   (`android-runtime.md` §8).
5. **Split `routes.py` and the route modules so `include_router` imports lazily per feature.** This is
   architectural and lower priority; measure after 1–4.
6. Keep the warm-up in `Application.onCreate` on a background thread, as the spike does, so the
   2.2 s overlaps the first frame and the UI cache render.

### Memory (PSS)

`dumpsys meminfo` TOTAL PSS (`tools/memory.sh`):

| State | App PSS |
|---|---|
| Baseline: same APK, Python not started (`files/no-python`) | 38.8 MB |
| Engine idle (API + worker, 30 s after ready) | 185–192 MB |
| Engine busy (peak during 200 MB upload) | 199.8 MB |
| Idle after upload | 194.4 MB |

**Python/engine share ≈ 150–155 MB idle** (idle minus baseline). **Budget ≤ 120 MB: miss by ~27 %.** Idle
breakdown: anonymous "Unknown" 71.7 MB (pymalloc arenas), Native Heap 52.8 MB, `.apk mmap` 24.8 MB (Chaquopy's
Python zips read in place), `.so mmap` 15 MB, Dalvik 12 MB. Busy adds only ~8 MB, because the upload path
streams. Cuts: the same lazy-import items above, since 1,357 modules is mostly import residue (alembic, Telethon
TL types, OpenAPI models); then measure what remains with `tracemalloc` snapshots after warm-up to find the
largest retained allocations. Re-measure on the reference device; emulator PSS for shared file pages is not
authoritative.

### APK size

Release-shaped build (pyc only, no minify), one ABI per build (`-PbentoAbis=`):

| ABI | APK file | Download (apkanalyzer) | bundletool `get-size total` (AAB with both ABIs) |
|---|---|---|---|
| arm64-v8a | 41.2 MB | **29.1 MB** | 35.9 MB |
| x86_64 | 41.5 MB | 29.6 MB | 36.1 MB |

Budget ≤ 60 MB arm64 download: **pass**. Largest entries: Python requirements 15.3 MB (sqlalchemy 3.5,
telethon 2.1, pydantic-core 1.9, cryptography 1.2), `libpython3.13.so` 5.4 MB, `libcrypto_python.so` 4.5 MB,
stdlib 5.8 MB, `classes.dex` 3.8 MB (debuggable, no R8). Note: Chaquopy puts per-ABI Python assets
(`requirements-<abi>.imy`, `stdlib-<abi>.imy`) in the base module's `assets/`. App Bundle ABI splits therefore do
not separate them, and every device downloads both ABIs' Python native code (~6 MB extra). Stage 22 should use
per-ABI flavors / multi-APK or Play asset-pack targeting. Chaquopy also refuses AGP `splits.abi` (it requires
`ndk.abiFilters`).

### Throughput

The fake cloud is local disk, so these numbers measure the device-side cost of the v2 path. They are not
network numbers. x86_64: encrypted upload ≈ 60 MB/s, download + decrypt 60–66 MB/s, both ≫ 8 MB/s. The
"with/without `cryptg`" comparison applies only to MTProto (Telethon AES-IGE), not to the v2 blob path, which
uses `cryptography` AES-GCM. Without `cryptg`, Telethon cannot reach the budget (see Crypto ceilings).

### Not measured

- Floor device (4 GB, Android 10) and reference device (Pixel 7a / Galaxy A35): pending owner device list.
- Wi-Fi throughput against real Telegram with and without `cryptg`: pending owner.
- Battery drain over 1 h idle with the engine stopped: needs a physical device (emulator battery is simulated).
- Unix domain socket transport (step 8, stretch): not attempted.

## Required backend changes (for agent 35)

The spike runs with exactly these monkeypatches and deviations (`bento_spike/patches.py`, `engine.py`,
`requirements-android.txt`):

1. **watchdog at import time.** `interfaces/worker/main.py` imports `adapters/backup/watcher.py`, which does
   `from watchdog.events import FileSystemEventHandler` at module level. watchdog is not in the `android`
   profile, so the spike stubs the module. Fix: make the watcher import lazy, or choose the watcher in
   `infrastructure/services.py` by platform (MediaStore on Android).
2. **Migrations location.** `launcher._bundle_root()` resolves `alembic.ini`/`migrations/` relative to `apps/api`
   (or PyInstaller's `_MEIPASS`). The spike repoints it at an extracted `bento_migrations` package. Fix: ship
   migrations inside the package (for example `bento/migrations/` + programmatic `Config`) or let
   `interfaces/android/engine` pass the path; it needs a real directory (`extractPackages`).
3. **Media generation seam.** `MediaProcessingService` gets a concrete `LocalMediaGenerator` (Pillow, pypdfium2,
   ffmpeg) from `worker/main.py::_create_dispatcher`. The spike replaces `_generate_image` with the `MediaTools`
   bridge. Fix: a generator/thumbnailer port with `adapters/android/media_tools.py` (images via ImageDecoder,
   video via MediaMetadataRetriever, PDF via PdfRenderer; Pillow as fallback), wired by platform.
4. **Import-cost cuts** for engine ready and PSS: move `bind_loopback_listener` and the migrations runner out of
   `interfaces/desktop/launcher.py` (no alembic/argparse import on the hot path), add an at-head fast check
   without alembic, make Telethon lazy, and avoid OpenAPI model construction at startup (see the profile).
5. **`cryptography` pin.** The backend pins `>=46,<47`, but the newest Android build is 42.0.8 (Chaquopy repo).
   The backend's used APIs (AESGCM, X25519, HKDF, HMAC, hashes, `Cipher`, `constant_time`, `InvalidTag`) all exist
   in 42, and the fake-cloud flows pass. Fix, in order of preference: build cryptography 46 for Android in CI
   (Rust + Chaquopy's OpenSSL 3.5), or make the `android` extra pin `cryptography==42.0.8` with a marker and run
   the crypto unit tests against 42 in CI.
6. **`android` extra in `pyproject.toml`**, as in `requirements-android.txt`: `uvicorn` without `[standard]`,
   `pillow`, and **`cryptg` (mandatory, see Crypto ceilings)**; exact pins from `uv.lock`; Python 3.13. Note that
   Telethon resolved to 1.46.0 because the spike used ranges.
7. **Device platform.** The host reports the Android guest as `platform: other`. Add `android` to the device
   platform values used in pairing and device listings (and in the Telegram device model if it is
   platform-specific).
8. **In-memory configuration.** The spike calls `process_secrets.adopt_environment_secrets(names, environ=<private
   mapping>)` to inject the API token and wrapping key without touching `os.environ`, and it sets non-secret
   settings through `os.environ` before `get_settings.cache_clear()`. Fix: `engine.configure(...)` builds `Settings`
   explicitly and adds a `process_secrets.put()`. It should also skip `dotenv_values(".env")`, which on Android
   reads from cwd `/`.
9. **Wheels and index.** CI must build `pydantic-core` (exactly the version `pydantic` pins) and `cryptg` for
   `android_24_arm64_v8a` and `android_24_x86_64` (`wheels/build_rust_wheel.sh` includes the `EXT_SUFFIX` rename),
   plus pure wheels for sdist-only `pyaes` and `hkdf`, and publish them to the internal index. Chaquopy 17 will not
   build sdists.
10. Not required, but recommended: streaming per-part encryption, or a free-space check, for large uploads (see
    §3 observation).

No backend code was edited in this stage.

## Pending owner (exact steps)

Real Telegram needs a test account and Bento's `api_id`/`api_hash`. Never commit or log them.

1. Install a debug build on a physical phone:
   `cd spikes/android-engine && wheels/build_all.sh && BENTO_BUILD_PYTHON=$PWD/wheels/work/buildenv/bin/python tools/build_install.sh -PbentoAbis=arm64-v8a`.
2. Real backend: write Bento's app credentials to an app-private file without passing them through intents or
   logs: `adb shell run-as dev.bento.spike sh -c 'cat > files/telegram-app.json' < telegram-app.json`, where the
   local file holds `{"api_id": …, "api_hash": "…"}`. Keep that file outside the repo. Then run
   `tools/act.sh ready '{"storage_backend":"telegram"}'` in a fresh process. Delete the file afterwards
   (`run-as … rm files/telegram-app.json`).
3. QR login: `tools/act.sh fake_login_vault '{"method":"qr"}'` shows `qr_pending`. Scan the QR from Telegram
   on another phone (Settings → Devices → Link Desktop Device). Expect `authorized`, then vault `ready`.
4. Phone login: `'{"method":"phone","phone":"+…","code":"<code from Telegram>"}'` (add `"password"` if 2FA).
   Run it in two steps if the code arrives late (`/login/phone`, then `/login/code`).
5. Throughput + resume on Wi-Fi: `tools/act.sh upload_big '{"size_mb":200}' 1800`, then
   `tools/act.sh download_big`, then `upload_then_kill '{"size_mb":200,"kill_after_parts":1}'` (use
   `BENTO_TELEGRAM_PART_SIZE_MB=64` via the `part_size_mb` option) and `resume_check`. Repeat with a build that has
   `-PbentoCryptg=false`. Record MB/s from `remote_upload_wait_s` and `download_big.mb_s`.
6. Same-phone `tg://login?token=`: with the Telegram app installed and signed in on the same phone, take the
   `qr_url` from `POST /api/account/login/qr` and open it with
   `adb shell am start -a android.intent.action.VIEW -d '<qr_url>'`. Record (screenshots) whether Telegram shows
   the login confirmation and whether `/api/account` becomes `authorized`. If it does not, phone-number login
   becomes the primary path (`android-runtime.md` §12.6; not a no-go).
7. Floor and reference devices: run `tools/cold_starts.sh 20` and `tools/memory.sh` on each. For battery, run
   `adb shell dumpsys batterystats --reset`, leave the app in the background for 1 h with the engine stopped
   (process idle), then `dumpsys batterystats dev.bento.spike`.

## Risks

- **Floor-device cold start** is the main unknown: 2.9 s p50 on a desktop-class x86_64 core already misses the
  2.5 s p50. Without the import cuts the floor device will likely miss p90 too.
- **Python PSS** is over budget by 27 % and needs the cuts. Low-RAM devices kill background processes holding
  ~190 MB more readily.
- **Wheel supply chain**: two Rust wheels built in-house per Python × ABI. Python 3.14+ would add cryptography,
  pillow, cffi, and greenlet to that list until the Chaquopy repo catches up. Pin Python 3.13 for v1.
- **cryptography 42 vs 46** drift between desktop and Android until change 5 lands.
- **Temp disk for large uploads** (full ciphertext copy) on storage-constrained phones.
- **Process freezing** (for agent 36): an engine process with no holder is frozen by the cached-app freezer and
  its loopback API hangs mid-request (seen with the unbound `:host` service). Every engine use must sit inside a
  §3 holder, and the UI client must treat a stalled loopback call as `Degraded`, not wait forever.
- Chaquopy is a single-vendor dependency (Apache-2.0, actively released; 17.2.0 shipped 2026-10-26).

## Reproduce

```bash
export JAVA_HOME=$HOME/.local/share/mise/installs/java/temurin-17
cd spikes/android-engine
wheels/build_all.sh        # local Android wheels → wheels/dist (~2.5 min; verified from scratch)
export BENTO_BUILD_PYTHON=$PWD/wheels/work/buildenv/bin/python   # CPython 3.13 created by build_all.sh (absolute path)
tools/build_install.sh     # debug APK, both ABIs (-PbentoAbis=x86_64 for one; -PbentoCryptg=false without cryptg)
tools/act.sh ready; tools/act.sh health; tools/act.sh thumbnail; tools/act.sh fts5
tools/act.sh fake_login_vault '{"method":"qr"}'
tools/act.sh upload_big '{"size_mb":200}' 900; tools/act.sh download_big
tools/act.sh upload_then_kill '{"size_mb":200,"kill_after_parts":2}'; tools/act.sh resume_check
tools/act.sh aes_bench '{"mb":32}'
tools/cold_starts.sh 20 results/raw/cold.jsonl; tools/memory.sh
# pairing: uv run --project apps/api --no-dev python spikes/android-engine/tools/relay_double.py → ws://127.0.0.1:P
#   adb reverse tcp:P tcp:P, then (fresh process) ready with guest options, start_host, host_seed, pair_guest
```
