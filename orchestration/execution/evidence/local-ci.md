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

### Local CI PASS — `4ef5c6d1d7` (HEAD)

- Commit `4ef5c6d1d7e528032b2daec8fd0a9e1ee0bb8e52` · tree `2a223c6e05684fc7bbb476259bba0b9ee44940bb` · Smart search: relevance threshold and hybrid ranking calibrated on the real model
- Ran 2026-11-27T01:52:39-05:00 on Linux 7.2.15-6-omarchy (16 CPU, 15 GB RAM) · total 3m29s
- Toolchain: uv 0.12.5 · node v24.22.3 · java 17.0.20.1 · script `dac376919d`
- Logs: `/home/jc/.cache/bento-local-ci/runs/4ef5c6d1d7-20261127-014910`

| Component | Step | Result | Time | Detail |
|---|---|---|---|---|
| backend | uv-sync | PASS | 1s |  |
| backend | pytest | PASS | 3m27s | 1944 passed, 3 skipped, 13 deselected, 5 warnings in 203.12s (0:03:23) |
| release | unittest | PASS | 1s | Ran 57 tests in 1.274s |
| release | version-check | PASS | 0s |  |
