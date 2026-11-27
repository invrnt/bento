# Local CI Evidence

Append-only log written by `scripts/local-ci.sh --record orchestration/execution/evidence/local-ci.md` (see `../local-integration.md` §5). Each entry names the tested commit and tree. Commit evidence on its own, touching only this file. Full logs stay in `~/.cache/bento-local-ci/runs/`, outside git.

<!-- First entry: validation run of the script itself (an earlier revision, hence its script hash; site counts were not parsed yet: 50 pass). -->

### Local CI PASS — `0b611cfa64` (feature/android)

- Commit `0b611cfa6481dc7418d04fc15e7bc67efd71703a` · tree `92c34cfda12cfeee1e2dca126f3dc44667440a1b` · Backend: read camera EXIF (DateTimeOriginal, exposure) from the Exif sub-IFD
- Ran 2026-11-24T09:43:41-05:00 on Linux 7.2.15-1-omarchy (16 CPU, 15 GB RAM) · total 2m32s · parallel lanes
- Toolchain: uv 0.12.5 · node v24.22.3 · java 17.0.20.1 · script `8219883eab`
- Logs: `/home/jc/.cache/bento-local-ci/runs/0b611cfa64-20261124-094109`

| Component | Step | Result | Time | Detail |
|---|---|---|---|---|
| backend | uv-sync | PASS | 34s |  |
| backend | pytest | PASS | 1m58s | 1271 passed, 13 deselected, 5 warnings in 114.93s (0:01:54) |
| site | test | PASS | 0s |  |
| relay | npm-ci | PASS | 1m13s |  |
| relay | typecheck | PASS | 5s |  |
| relay | vitest | PASS | 4s | Tests 74 passed (74) |

### Local CI PASS — `3c0e507e85` (HEAD)

- Commit `3c0e507e85ecdc04ffe651f372d161af98f3ea12` · tree `0838053f5fb2838df5f40c4607295df9165f674b` · Smart search: download resilience to network failures
- Ran 2026-11-27T01:56:35-05:00 on Linux 7.2.15-6-omarchy (16 CPU, 15 GB RAM) · total 3m05s
- Toolchain: uv 0.12.5 · node v24.22.3 · java 17.0.20.1 · script `dac376919d`
- Logs: `/home/jc/.cache/bento-local-ci/runs/3c0e507e85-20261127-015329`

| Component | Step | Result | Time | Detail |
|---|---|---|---|---|
| backend | uv-sync | PASS | 0s |  |
| backend | pytest | PASS | 3m05s | 1917 passed, 1 skipped, 13 deselected, 5 warnings in 180.98s (0:03:00) |
