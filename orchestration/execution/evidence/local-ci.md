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
