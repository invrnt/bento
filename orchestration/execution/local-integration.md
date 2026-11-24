# Local Integration and Local CI

GitHub Actions is not available for this repository (the account has no billing), so nothing in `.github/workflows/` runs. Every check CI would run happens on the orchestrator's machine instead, through `scripts/local-ci.sh`, and the results are written to a versioned evidence log. This document covers how the open agent branches are merged into `feature/android`, what the local gate runs, and how changes reach `main` and a signed APK without CI.

Machine budget: 16 CPU, ~15 GB RAM (usually only 2-3 GB free while agents run), ~90 GB disk. There is one shared AVD (`bento_spike_api35`), always used under `flock ~/.cache/bento-android-emulator.lock`. Never run `gradle --stop`, because other agents' daemons are live.

## 1. Branches and merge order

All merges go into `feature/android` (local, not pushed), with `git merge --no-ff <branch>` from the main checkout `/home/jc/dev/personal/bento`. `git rerere` is already enabled (`rerere.enabled=true`). Keep it enabled so that a conflict resolved during a preview or an aborted merge is replayed when the merge is done for real.

| # | Branch (worktree) | Stage | Base | What it touches | Why this position |
|---|---|---|---|---|---|
| 1 | `t3/android-backend-gaps` | 21b | `0b611cf` (tip) | `apps/api` only, migration 0008, new/changed HTTP fields | Backend first: 41 and 22a consume its fields. No Android files, so the merge is clean, but it makes `core/api/openapi.json` stale. |
| 2 | `t3/android-backup-settings-activity` | 21 / agent 41 | `140a938` (behind 39 and the shell fix); tip `4dc79c3` at planning time | `feature/activity`, `feature/settings`, `core/background`, `app/` registrations, icons, strings | Last Stage 21 feature. It conflicts with the 39 merge (see §2). Stage 21's exit gate (journeys 1-15) is run after this merge. |
| 3 | `t3/android-local-release-updater` | 22a | `0b611cf` | `core/update` (new module), the `app/build.gradle.kts` release/signing block, `libs.versions.toml`, an updater entry in Ajustes | Needs Settings (41) in place. The signing config it adds is also what 22b's `assetlinks.json` fingerprint must match. |
| 4 | `t3/android-site-release-pages` | 22b | `0b611cf` | `apps/site/**`, App Links (`assetlinks.json`, an `autoVerify` intent filter in the app manifest), `docs/**`, `README.md` | Needs the release certificate fingerprint from 22a, and its manifest change lands on top of 41's manifest edits. |
| 5 | `t3/android-security-review` | 22c | `0b611cf` | Report under `orchestration/` (docs only) | Can merge at any point without conflicts. Each high or medium finding becomes a fix commit or task, landed before 6. |
| 6 | `t3/android-copy-a11y-review` | 22d | `0b611cf` | Report plus a patch to `core/strings/**` (es + en) and content descriptions across features | Must go after every branch that adds strings (41, 22a, 22b, 22c fixes) so the patch covers all copy. It changes text, so it re-records the affected Roborazzi goldens. |
| 7 | perf (baseline profiles / benchmarks) | 22 perf | after 6 | `apps/android/baselineprofile/`, `benchmark/`, `libs.versions.toml` (baselineprofile plugin), `app/build.gradle.kts` (`baselineProfile(project(...))`), the generated `baseline-prof.txt` | The profile has to be generated from the final UI, so it is last. The generated profile is regenerated on the emulator, never merged by hand. |

Branches 5 and 6 are reports. Merge the report commit as-is. The 22d patch is the only one of the two that changes code and needs the gate.

### Previewing a merge without touching any checkout

```sh
git merge-tree --write-tree --name-only feature/android <branch>   # exit 1 + list = conflicts
```

Run on `feature/android@0b611cf`, this already predicts the following for 41: content conflicts in `settings.gradle.kts`, `app/build.gradle.kts`, `BentoNavGraph.kt`, `scripts/icons.json`, `BentoIcons.kt`, and the five `core/designsystem/screenshots/icons/*.png` goldens. `Routes.kt` and `AndroidManifest.xml` auto-merge. For 21b the preview is clean.

Measured wall time for the light lanes (`--backend --site --relay --parallel`, warm uv cache, ~1 GB free): 2m32s. Expected totals: `--merge --parallel` ≈ 10 min (Android lane dominates), `--full` ≈ 35-40 min (≈15 min light + Android full ≈15 min + journeys ≈15-20 min, partially overlapping with `--parallel`), plus `--desktop-native` ≈ 20 min and `--benchmarks` ≈ 25 min before a PR to `main`.

### Rebase or merge?

Merge, don't rebase. The agent branches live in worktrees that other sessions still have checked out, and a merge keeps their SHAs (and the evidence recorded against them) valid. If a branch is far behind (41 is three commits behind), the orchestrator can ask the agent to `git merge feature/android` into its own branch first, so the agent resolves its own conflicts with full context. That is preferred whenever the agent is still running.

## 2. Conflict types and how to resolve each

| Type | Files | Resolution |
|---|---|---|
| One-line registries (append-only) | `settings.gradle.kts` (`include(...)`), `app/build.gradle.kts` (`implementation(project(...))`), `Routes.kt` (one `@Serializable` key per destination), `BentoNavGraph.kt` (one `entry<Route.X>` line + imports), `AndroidManifest.xml` (components, shortcuts meta-data) | Keep both sides. Order: existing entries first, then the incoming ones, grouped by feature. Imports: take the union, then let `ktlintFormat` sort them (`./gradlew :app:ktlintFormat`). Check with `:app:compileDebugKotlin`. rerere records each resolution. |
| Version catalog | `gradle/libs.versions.toml` | Take the union of `[versions]`, `[libraries]` and `[plugins]`. If both sides bump the same version, keep the higher one only if the other branch's tests pass with it. Otherwise ask that agent. Never keep two aliases for the same coordinates (AGENTS.md: no duplicates). |
| Icon registry (source of a generated file) | `scripts/icons.json` | Take the union by `name`; `--ours`/`--theirs` alone drops icons. During the conflicted merge: `jq --indent 2 --slurpfile t <(git show :3:apps/android/scripts/icons.json) '.icons as $o \| .icons = $o + [ $t[0].icons[] \| select(.name as $n \| ($o \| map(.name) \| index($n)) == null) ]' <(git show :2:apps/android/scripts/icons.json) > apps/android/scripts/icons.json`. Tested on `feature/android` × 41: 86 base + 9 + 14 = 109 icons, same formatting as the committed file. If both sides changed the same icon, fix that entry by hand. Then `npm --prefix apps/android/scripts test`. |
| Generated sources | `core/designsystem/.../generated/BentoIcons.kt`, `BentoTokens.kt`, `bento_colors.xml` | Never resolve by hand. Take either side (`git checkout --ours <file>`), then regenerate: `npm --prefix apps/android/scripts run generate` (after `npm ci --prefix apps/android/scripts`). `:core:designsystem:verifyBentoGenerated` must pass. |
| Generated goldens (binary) | `core/designsystem/screenshots/icons/*.png`, any Roborazzi PNG | Take either side, then re-record from the merged sources: `./gradlew :core:designsystem:recordRoborazziDebug --tests 'dev.bento.designsystem.PrimitiveScreenshotTest' -PbentoBuildPython=…`. Confirm that `git status` shows only the PNGs you expected (icons/ for an icon merge). Then `verifyRoborazziDebug` must pass. Look at the new PNG before committing. |
| OpenAPI snapshot | `core/api/openapi.json` (generated from the backend) | Never merge it. After any merge that touches `apps/api/src/**`, run `./gradlew :core:api:updateOpenApiSnapshot` (needs `uv`), then `:core:api:checkOpenApiDrift` and a build (the Kotlin DTOs are regenerated by `generateOpenApiKotlin`). Commit it in the merge commit, or as `Regenerate OpenAPI snapshot` right after it. After 21b this is mandatory: its new fields must appear in the DTOs 41 and 22a use. |
| Python requirements for Chaquopy | `python-wheels/requirements-android.txt` | Regenerate with `python-wheels/generate_requirements.py` if `apps/api/pyproject.toml` or `uv.lock` changed. `checkPythonRequirements` (part of `check`) verifies it. |
| Strings | `core/strings/src/main/res/values{,-en}/strings_<feature>.xml` | Feature-owned files rarely conflict. In shared files (`strings_common.xml`, `strings_notifications.xml`, `strings_shell.xml`), keep both sides and remove duplicate keys. If both sides define the same key with different text, 22d's wording wins, otherwise the owning feature's. es and en must keep the same key set (Android lint `MissingTranslation` in `check`). |
| Docs / site | `README.md`, `docs/**`, `apps/site/**` | Merge by hand. `--site` runs the docs link checker over README.md and docs/**. |
| Migrations | `apps/api/migrations/versions/*` | Only 21b adds one (0008). If another branch adds a migration, it must be renumbered on top of `down_revision`, never merged as two heads. `alembic heads` must print exactly one head (covered by the backend suite). |

After resolving a merge: `git diff --check` (no conflict markers or whitespace), run the per-merge gate (§4), then commit the merge.

## 3. The local gate (what replaces CI)

`scripts/local-ci.sh` checks out the commit under test in a throwaway detached worktree (`~/.cache/bento-local-ci/wt/<sha>-<ts>`), so it never touches a working checkout, and removes it at exit (`--keep` keeps it). Every step runs under `systemd-run --user --scope -p MemoryMax=…` at `nice 10`, with one log per step in `~/.cache/bento-local-ci/runs/<sha>-<ts>/`. At the end it writes a markdown summary (`summary.md`) with the commit, tree, toolchain, a pass/fail/duration/count row per step, and failure tails.

| Flag | Mirrors | Commands (exactly as CI or the pre-push hooks run them) | Mem cap | Approx. time |
|---|---|---|---|---|
| `--backend` | desktop-native.yml "Install locked dependencies" + "Test backend" | `uv sync --project apps/api --frozen --extra dev --extra desktop`; `cd apps/api && uv run --frozen pytest` | 3G | sync ~0.5 min (warm uv cache); suite ~2 min (measured: 1271 passed in 1m55s) |
| `--backend-smoke` | `make smoke` + Android HTTP tests | `pytest tests/smoke tests/api/android` | 3G | <10 s (8 tests) |
| `--web` | desktop-native.yml + pre-push hooks | `npm ci`; `npm test`; `npm run build` (`tsc -b && vite build`, which catches `tsconfig.node.json` errors that `tsc -p tsconfig.app.json` misses) | 2G | ~3 min |
| `--desktop` | desktop-native.yml "Test … desktop" | `npm ci` (web + desktop); `npm test`; `npm run build:main` | 2G | ~3 min |
| `--desktop-native` | the `linux-x64 unsigned package` required check | `write-build-config.mjs`; `npm --prefix apps/desktop run make`; `smoke:packaged`; `verify:artifacts` | 4G | ~15-20 min |
| `--site` | (no workflow) `apps/site` `npm test` | `node scripts/build.mjs && node --test test/*.test.mjs` (includes the docs link checker) | 2G | <5 s (50 tests) |
| `--relay` | (no workflow) `apps/relay` | `npm ci`; `npm run typecheck` (`wrangler types --check` + both tsconfigs); `npm test` (workers pool) | 2G | ~1.5 min (npm ci ~1 min, 74 tests) |
| `--android-fast` | android.yml `checks`, minus Android lint and the release/both-ABI assemble | generators `npm ci && npm test`; `:core:designsystem:verifyBentoGenerated :core:api:checkOpenApiDrift ktlintCheck detekt testDebugUnitTest verifyRoborazziDebug :app:assembleDebug` | 5G | ~6-8 min warm |
| `--android-full` | android.yml `checks` in full + the androidTest APK | generators; `-p build-logic :convention:test`; `check :core:designsystem-lint:test` (check = ktlint, detekt, lint, unit, Roborazzi, drift, requirements); `:app:assembleDebug :app:assembleRelease :app:assembleDebugAndroidTest -PbentoAbis=arm64-v8a,x86_64` | 5G | ~15 min |
| `--journeys` | android.yml `emulator` (API 35 locally instead of 29 + 36) | under the emulator flock: boot the AVD if none is attached, disable animations, `:app:connectedDebugAndroidTest :smoke:connectedCheck -P…notClass=dev.bento.smoke.StartupBenchmark`, shut down the AVD only if this run booted it | 7G (AVD included) | ~15-20 min + lock wait |
| `--benchmarks` | android.yml nightly Macrobenchmark + photos journeys | `:smoke:connectedCheck -P…class=…StartupBenchmark`; `:feature:photos-benchmark:connectedCheck` | 7G | ~20-30 min |

Every step also has a timeout (`--step-timeout`, default 45 min; 2 h for Android, emulator and desktop-native steps). Under memory pressure vitest/workerd were seen to report errors and then hang instead of exiting, and a hung step must not hold the emulator lock forever.

Presets: `--light` (backend web desktop site relay), `--merge` (light + android-fast), `--full` (light + android-full + journeys). `--auto <base>` picks components from the paths changed in `<base>...<ref>`, using the same path filters as `android.yml`. A backend source change also selects android-fast, because of OpenAPI drift and the embedded engine.

Toolchain the script pins (CI parity):

- Node 24 from mise (`~/.local/share/mise/installs/node/24`, installed with `mise install node@24`). The system Node 26 is not used: desktop's `engines` is `<26`, and npm on Node 26 refuses its git dependency.
- `uv` 0.12.5 with `--frozen`.
- JDK 17 temurin (`$BENTO_JAVA17`) and `-PbentoBuildPython` = uv's CPython 3.13.
- Gradle with `--no-daemon --max-workers=3 -Dorg.gradle.jvmargs=-Xmx2g -Pkotlin.compiler.execution.strategy=in-process`. No daemon is left behind holding 2 GB, the run never touches other agents' daemons, and the Kotlin compiler stays inside the memory scope.
- The Android cp313 wheels are not in git. They are symlinked from the main checkout's `apps/android/python-wheels/dist` (`$BENTO_ANDROID_WHEELS`). `local.properties` is written with `sdk.dir`.

Differences from CI that remain, and must be accepted explicitly:

- The Windows and macOS desktop packages (three of the four required checks) cannot be built on this Linux machine. PyInstaller hidden imports and Windows path/env issues are therefore unverified.
- The emulator runs API 35 only, not 29 + 36.
- Nothing runs on a schedule (the nightly jobs).

### Running parts in parallel within the RAM budget

`--parallel` runs three lanes at once: python (backend), TS (web → desktop → desktop-native → site → relay, in that order inside the lane, because desktop reuses `apps/web/node_modules`), and Android (fast/full → journeys → benchmarks, serial). Before starting each lane, the script waits until `MemAvailable` is at least `--min-free-mb` (default 1500 MB), for up to `--mem-wait` seconds (default 600). After that it proceeds and records a warning in the summary.

Rules of thumb with 2-3 GB free:

- The python and TS lanes together peak at about 2.5 GB. Run them in parallel whenever no Gradle build of another agent is running.
- Never run more than two Gradle builds at once on the machine, counting other agents'. While another agent is building, run the Android lane alone (without `--parallel`).
- Journeys and benchmarks take the emulator lock. If another agent holds it, the step waits for up to `BENTO_EMULATOR_LOCK_WAIT` (3600 s) rather than failing.
- Disk: each run's worktree (node_modules, `.venv` hardlinked from the uv cache, Android `build/`) costs 1-4 GB and is deleted at exit. Logs stay in `~/.cache/bento-local-ci/runs`. Prune them by hand when they pass ~5 GB.

## 4. What runs when

| Moment | Gate | Command |
|---|---|---|
| Before merging an agent branch | The agent's own tests (its handoff), plus `git merge-tree` preview | `git merge-tree --write-tree --name-only feature/android <branch>` |
| After each merge commit (smoke) | Components touched by the merge, android-fast for any Android or backend change, `--backend` whenever `apps/api` changed | `scripts/local-ci.sh --ref feature/android --auto <pre-merge-sha> --parallel --record orchestration/execution/evidence/local-ci.md` |
| Report-only merges (22c, 22d reports) | `--site` (doc links) | `scripts/local-ci.sh --ref feature/android --site` |
| End of Stage 21 (after #2) and end of Stage 22 (after #7) | Full gate + journeys | `scripts/local-ci.sh --ref feature/android --full --record …` |
| Before a PR to `main` | Full + `--desktop-native` (the only required check reproducible here) + `--benchmarks` | `scripts/local-ci.sh --ref feature/android --full --desktop-native --benchmarks --record …` |
| Release tag | Full + benchmarks on the tagged SHA, then §7 | as above with `--ref android-vX.Y.Z` |

If a merge's smoke fails, fix it in a follow-up commit on `feature/android` (or hand it back to the agent) before the next merge. Never stack merges on a red tip. If the failure can't be fixed quickly, `git reset --hard <pre-merge-sha>` the integration branch; it is local and unpublished, and rerere keeps the resolution.

## 5. Evidence (instead of GitHub checks)

- Every gate run passes `--record orchestration/execution/evidence/local-ci.md`. That appends the summary to the versioned log: the commit SHA, the tree SHA, the date, the toolchain, the per-step result with counts (`1300 passed`, `Tests 120 passed`, `BUILD SUCCESSFUL in …`), the script blob hash, and failure tails.
- Commit the evidence as its own commit that touches only that file: `git add orchestration/execution/evidence/local-ci.md && git commit -m "Local CI evidence for <short-sha>"`. Because the commit changes nothing else, a reviewer can check that the code is exactly what was tested with `git diff --stat <tested-sha> HEAD -- . ':!orchestration/execution/evidence'` (empty output).
- The tree SHA is what ties evidence to `main`. A squash merge creates a new commit SHA but the same tree, so `git rev-parse main^{tree}` must equal a tree recorded with `PASS`. If `main` moved in between, the squash tree differs and the gate must run again on the PR head after `git merge main`.
- Full logs stay outside git (`~/.cache/bento-local-ci/runs/<sha>-<ts>/`). Attach the relevant ones to the PR as a gist or comment only if asked. Logs are redacted by the backend's own rules, but check them before attaching anything.

## 6. Reaching `main` without CI (owner decision)

Current protection on `main` (github.com/invrnt/bento): PR required, four required native checks (`linux-x64`, `windows-x64`, `macos-x64`, `macos-arm64` "unsigned package", strict/up-to-date), linear history (squash or rebase), admins enforced, 0 approvals. Without Actions billing those four checks can never report. The PR would also queue the workflows, which then fail or never start. As configured, no PR can merge, including the owner's own.

Options (the owner chooses; none has been changed):

1. **Local status as the required check (recommended).** Replace the four required contexts with a single `local-ci` commit status. After the gate passes on the PR head SHA, the owner posts it: `gh api repos/invrnt/bento/statuses/<sha> -f state=success -f context=local-ci -f description="local gate PASS (see evidence)"`. PR + linear history + up-to-date stay enforced. The evidence summary goes into the PR body. Trade-off: anyone with write access can post a status, which is acceptable for a single-maintainer repo.
2. **PR without required checks.** Keep PR + linear history + admin enforcement and drop the required status checks. The PR body carries the evidence summary, and the owner merges with squash. Simpler, but nothing mechanical blocks a merge without evidence.
3. **Local merge and direct push.** Turn off protection (or admin enforcement), squash `feature/android` locally onto `main`, push. This leaves no PR trail. Not recommended.

In every option, also decide whether to disable Actions for the repo (Settings → Actions) so that PRs don't show phantom failed or queued checks. Keep the workflow files so CI can be restored if billing returns. Also decide whether accepting only the `linux-x64` package check (plus no Windows/macOS packaging) is acceptable for a change set that is mostly Android plus backend; the backend change does affect the desktop sidecar.

The PR itself (once the owner allows it): squash of `feature/android` → `main`, with a body containing the program summary, the latest `--full --desktop-native --benchmarks` summary for the PR head, and links to the stage status in `android-program.md`.

## 7. Local release of the signed APK

Stage 22's exit gate says "built by CI from a tag". Without CI, the same steps run locally. 22a defines the exact Gradle properties and the update-manifest tooling; until it lands, take the names below as placeholders.

1. Prerequisites (owner): the release keystore, outside the repo and backed up offline (e.g. `~/.config/bento/android-release.jks`), with its passwords supplied through environment variables or `~/.gradle/gradle.properties`, never in git or logs; the production Telegram `api_id` / `api_hash` and `site_url` build values.
2. Tag on the commit that is (or will be) on `main`: `git tag -s android-vX.Y.Z <sha>`, with `versionCode`/`versionName` bumped in the same commit.
3. Gate: `scripts/local-ci.sh --ref android-vX.Y.Z --full --benchmarks --record …`. It must pass on exactly the tagged SHA.
4. Build in a clean worktree of the tag: `./gradlew :app:assembleRelease -PbentoAbis=arm64-v8a,x86_64 <22a signing props>` (no `--no-daemon` shortcuts; the same JDK and Python as the gate).
5. Verify:
   - `apksigner verify --verbose --print-certs app-release.apk`. The SHA-256 must equal the fingerprint in `apps/site/.../assetlinks.json` (22b).
   - `sha256sum` the APK.
   - Generate and sign the update-manifest entry with 22a's tool.
   - Install over the previous release on the emulator (and on a physical device) and confirm the in-app update from N-1 to N.
6. Publish (owner, outward-facing): `gh release create android-vX.Y.Z app-release.apk SHA256SUMS <manifest> --notes-file …`, then deploy the site (`npm --prefix apps/site run deploy`, which runs `check:placeholders` first).
7. Append the release evidence (tag, APK SHA-256, cert fingerprint, gate summary) to `evidence/local-ci.md`.

22a's prompt lists `.github/workflows/android-release.yml`. That workflow can be kept for the future, but the release of record is the local procedure above, and 22a should add a `scripts/`-level release script that implements steps 4-5.

## 8. Script reference

```sh
scripts/local-ci.sh --help
scripts/local-ci.sh --ref feature/android --merge --parallel --record orchestration/execution/evidence/local-ci.md
scripts/local-ci.sh --ref t3/android-backup-settings-activity --auto feature/android --dry-run
scripts/local-ci.sh --ref feature/android --full --desktop-native --benchmarks
```

The exit code is 0 when every step passes, 1 when any step fails, and 2 for a usage error. When a step fails, the later steps of that component are recorded as `SKIP`, and the other components still run. Overrides: `BENTO_JAVA17`, `BENTO_BUILD_PYTHON`, `BENTO_ANDROID_WHEELS`, `BENTO_CI_NODE_DIR`, `ANDROID_HOME`, `ANDROID_AVD_HOME`, `BENTO_AVD`, `BENTO_EMULATOR_LOCK`, `BENTO_EMULATOR_LOCK_WAIT`, `BENTO_CI_ROOT`.
