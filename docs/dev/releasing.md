# Releasing Bento

Releases are made on the maintainer's machines with `scripts/release/bento-release`. GitHub Actions is not
used (the repository has no Actions billing; see [GitHub Actions](#github-actions)). Nothing in this process
pushes, tags or publishes unless you run the explicit `publish` step.

Related: [Android release](android-release.md) (APK signing, update manifest, emulator dry run),
[desktop signing and updater manifests](../desktop/releasing.md) (Spanish), [local CI](../../orchestration/execution/local-integration.md),
[how users verify downloads](../user/en/verify-downloads.md).

## Versions and tags

Bento uses [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) with stable versions only
(`MAJOR.MINOR.PATCH`, no pre-releases). While Bento is `0.y.z`, a breaking change bumps `minor` and must
document the migration in the changelog.

| Thing | Version | Tag / identity |
|---|---|---|
| Desktop app, `bento` CLI, backend (`bento-api` wheel/sdist) | the product version | `vX.Y.Z`, the GitHub release marked **latest** |
| Android app | the product version (`versionName`; `versionCode = X·10⁶ + Y·10³ + Z`) | `android-vX.Y.Z`, a separate release with `--latest=false` |
| Pairing relay (`apps/relay`), public site (`apps/site`) | none: they deploy, they do not release | the deployed commit SHA ([relay](relay.md), [site](site.md)) |

- **Single source of truth:** the [`VERSION`](../../VERSION) file. `bento-release version check` proves that
  every manifest agrees: `apps/desktop` and `apps/web` `package.json` and `package-lock.json`,
  `apps/api/pyproject.toml`, the `bento-api` entry of `uv.lock`, `bento.__version__`, the settings default
  and registry. Android reads `VERSION` itself (`apps/android/app/build.gradle.kts`, after `-PbentoVersion` and
  an exact `android-v*` tag). The check runs in `scripts/local-ci.sh --light`.
- **One version line, two GitHub releases.** Android ships in its own release because the desktop updater
  reads `releases/latest`, and Android's in-app updater reads `android-v*` releases. Normally both tags point
  at the same commit. A version may ship on one channel only (for example an Android-only fix as
  `android-v0.1.1` with no `v0.1.1`); the changelog section says so.
- The CLI used to have its own `cli-v*` tags. They were never published and are retired: CLI archives are
  assets of `vX.Y.Z`, and `install.sh`/`install.ps1` read `releases/latest`.
- Tags are annotated and signed (`git tag -s`), are never moved or reused, and are created only on a
  reviewed commit of `main`.

### Bumping

```sh
scripts/release/bento-release version bump minor      # or major, patch, or an explicit 0.3.0
```

It rewrites `VERSION` and every manifest (text edits: formatting and comments survive) and turns
`## [Unreleased]` in `CHANGELOG.md` into `## [X.Y.Z] - <today>` with updated compare links. It refuses if the
manifests already disagree. For the first release (`0.1.0` is already the version) cut the changelog alone:

```sh
scripts/release/bento-release changelog cut            # [Unreleased] -> [0.1.0] - today
```

Commit the bump through a normal pull request.

## Changelog

[`CHANGELOG.md`](../../CHANGELOG.md) follows Keep a Changelog 1.1.0. Every pull request with a user-visible
change adds a line under `## [Unreleased]` in Added, Changed, Deprecated, Removed, Fixed or Security,
starting with the component in bold. `bento-release changelog check` validates the structure (local CI runs it)
and `bento-release changelog notes` prints a version's section. The release notes of both GitHub releases are
that section plus a "Verify your download" block.

## One-time setup (owner)

### Keys

| Key | What it signs | Where it lives | How the tool gets it |
|---|---|---|---|
| Release SSH key (Ed25519) | `SHA256SUMS` of each release (`SHA256SUMS.sig`) and, if you want, the git tags | your machine or a hardware token; never in the repository | `--signing-key <path>` or `BENTO_RELEASE_SIGNING_KEY=<path>`; a `.pub` path signs through ssh-agent |
| Update-manifest key (Ed25519 PEM) | `bento-update-*.json.sig` checked by the desktop and Android updaters | outside the repository, mode 600 | `BENTO_UPDATE_SIGNING_KEY_FILE=<path>`; public half in `BENTO_UPDATE_PUBLIC_KEY` |
| Android keystore | the APKs (v2/v3) | outside the repository | `BENTO_ANDROID_KEYSTORE*` ([Android release](android-release.md#one-time-owner-setup)) |
| Apple Developer ID, Windows Authenticode | macOS / Windows packages | the macOS / Windows build machine | [desktop signing](../desktop/releasing.md) (`BENTO_MAC_SIGNING=1`, `BENTO_WINDOWS_SIGNING=1`) |

The tool never generates, prints or copies a private key; it passes paths to `ssh-keygen`, and the update key
reaches only the child process that signs manifests. Tests use throwaway keys in temporary directories.

**Why `ssh-keygen -Y sign` and not minisign or GPG:** OpenSSH is already on Linux, macOS and Windows 10+, so
neither you nor a user verifying a download installs anything; the key can stay in ssh-agent or on a hardware
token; and one Ed25519 key can sign both the tags (`gpg.format=ssh`) and `SHA256SUMS`, because the
`bento-release` namespace keeps the two kinds of signature apart (a git signature, namespace `git`, never
verifies as a release signature). minisign would add a tool for every verifier; GPG adds a keyring, expiry and
web-of-trust questions for no gain here.

Create the release key once (choose a passphrase):

```sh
ssh-keygen -t ed25519 -C "Bento release signing" -f ~/.ssh/bento_release_ed25519
```

Then publish the public half: add one line to [`scripts/release/allowed_signers`](../../scripts/release/allowed_signers)
in a reviewed commit and remove the `[[COMPLETAR]]` line:

```sh
printf 'bento-release namespaces="bento-release" %s\n' "$(cut -d' ' -f1,2 ~/.ssh/bento_release_ed25519.pub)"
```

Also add the key to your GitHub account as a **signing key** so tags show as verified, and configure git:

```sh
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/bento_release_ed25519.pub
git config --global gpg.ssh.allowedSignersFile "$PWD/scripts/release/allowed_signers"   # lets `git tag -v` check
```

Rotation: add the new key line, sign the next release with it, and keep the old line with
`valid-before="YYYYMMDD"` while older releases are still offered. If the key leaks, remove its line, publish a
release signed with a new key, and say so in the changelog's Security section.

### Release environment

Keep a `release.env` outside the repository (mode 600) and `source` it in the shell that releases:

```sh
export BENTO_RELEASE_SIGNING_KEY=~/.ssh/bento_release_ed25519
export BENTO_TELEGRAM_API_ID=…  BENTO_TELEGRAM_API_HASH=…          # docs/dev/telegram-credentials.md
export BENTO_RELAY_URL=https://…  BENTO_PUBLIC_SITE_URL=https://…
export BENTO_UPDATE_PUBLIC_KEY=…  BENTO_UPDATE_SIGNING_KEY_FILE=~/secure/bento-update-signing-key.pem
export BENTO_ANDROID_KEYSTORE=…  BENTO_ANDROID_KEYSTORE_PASSWORD=…  BENTO_ANDROID_KEY_ALIAS=…  BENTO_ANDROID_KEY_PASSWORD=…
export BENTO_ANDROID_CERT_SHA256=…  BENTO_SITE_HOST=…
```

### Tools on the Linux machine

Python 3.11+, uv, Node.js 24 (`mise install node@24`; desktop packaging refuses Node 26), `ssh-keygen`, `gh`,
JDK 17 and the Android SDK for Android, and `dpkg-deb` + `fakeroot` for the `.deb` packages (Arch:
`sudo pacman -S dpkg fakeroot`). `npx` downloads `@cyclonedx/cyclonedx-npm@6.0.1` on first use; Gradle
downloads the CycloneDX plugin 3.6.1.

## What this Linux machine builds

| Component | `--only` name | Output |
|---|---|---|
| CycloneDX SBOMs: Python (`uv export --format cyclonedx1.5`, desktop extra), npm (`@cyclonedx/cyclonedx-npm` 6.0.1 on the web and desktop lock files) | `sbom` | `bento-X.Y.Z-python.cdx.json`, `bento-X.Y.Z-npm-{web,desktop}.cdx.json` |
| Backend wheel and sdist (`uv build`) | `backend` | `bento_api-X.Y.Z-py3-none-any.whl`, `bento_api-X.Y.Z.tar.gz` |
| CLI (PyInstaller), smoke-tested (`--version`, daemon start/status/stop), `.deb`, installers | `cli` | `bento-cli-X.Y.Z-linux-x64.tar.gz`, `bento-cli_X.Y.Z_amd64.deb`, `install.sh`, `install.ps1` |
| Desktop Linux x64 (Electron Forge), smoke-tested, verified | `desktop` | `bento-desktop_X.Y.Z_amd64.deb` (Forge names it after the npm package; not yet built on this machine, see below), `Bento-linux-x64-X.Y.Z.zip`, `bento-update-linux-x64.json`, `SHA256SUMS-linux-x64` |
| Android APKs via [`apps/android/scripts/release.sh`](android-release.md) | `android` | `bento-android-X.Y.Z-{arm64-v8a,universal}.apk`, `bento-update-android-*.json(.sig)`, `SHA256SUMS-android-X.Y.Z.txt` |
| Android SBOMs: Gradle (CycloneDX plugin 3.6.1 through an init script, `releaseRuntimeClasspath`) and the Android Python profile | `android-sbom` | `bento-X.Y.Z-android-{gradle,python}.cdx.json` |

On macOS and Windows the default is `desktop,cli`; on Linux arm64 it is `cli`.

Without `dpkg-deb` and `fakeroot` a dry run builds the desktop `.zip` only (no `.deb`, so no Linux update
manifest) and skips the CLI `.deb`, and says so in `REPORT.md`; a release build refuses. The `.deb` file names
above are Forge's and `build_deb.sh`'s defaults and were not built during the tool's first dry run (no `dpkg` on
that machine): check them on the first real build.

**Windows and macOS are not cross-built.** The desktop app embeds a PyInstaller sidecar, and PyInstaller
only builds for the system it runs on; Squirrel.Windows also needs Windows (or Wine and Mono), and macOS
signing and notarization need macOS. The packaging uses Electron Forge, not electron-builder, and switching
would not remove the PyInstaller limit. So Windows and macOS artifacts are built on those machines with the same
tool and imported (below).

## Releasing, step by step

1. **Changelog and version.** On a branch: `bento-release version bump <kind>` (or `changelog cut` for the
   first release), review `CHANGELOG.md`, open the pull request and merge it.
2. **Local CI on the merged commit** of `main` (Actions does not run):

   ```sh
   git switch main && git pull --ff-only
   scripts/local-ci.sh --full --record orchestration/execution/evidence/local-ci.md
   ```

   Commit the evidence entry alone (it may be the commit you release; the release check accepts a PASS for an
   ancestor that differs only in that file).
3. **Dry run** (default; needs no tag, no clean tree, no production credentials):

   ```sh
   scripts/release/bento-release                        # = build, everything this machine can
   scripts/release/bento-release build --only desktop,cli --signing-key ~/.ssh/bento_release_ed25519
   ```

   Output: `dist/release/X.Y.Z/` with `vX.Y.Z/`, `android-vX.Y.Z/`, `notes/`, `logs/`, `REPORT.md` and
   `report.json`. `REPORT.md` lists what was built, every target still missing, and whether `SHA256SUMS` is
   signed. Android dry-run APKs use a throwaway keystore and a local update feed. **Dry-run output can never be
   published** (`publish` refuses it).
4. **Tags** on the release commit (local only):

   ```sh
   scripts/release/bento-release tag                    # git tag -s vX.Y.Z and android-vX.Y.Z at HEAD
   ```

5. **Release build** with the production environment sourced:

   ```sh
   source ~/secure/release.env
   scripts/release/bento-release build --release
   ```

   It refuses unless the tree is clean, both tags are signed and point at HEAD, a local-CI PASS is recorded,
   `allowed_signers` lists a key, the Telegram/relay/site build values and both signing keys are set, and
   `dpkg-deb`/`fakeroot` exist. It stops at the first failing component.
6. **Windows and macOS** (each machine, same commit, see below), then `import` their folders.
7. **Check** `dist/release/X.Y.Z/REPORT.md`: every target present, `SHA256SUMS signed: yes`, no unsigned update
   manifest. Verify as a user would: `bento-release verify dist/release/X.Y.Z/vX.Y.Z`.
8. **Publish** (explicit; see [Publishing](#publishing)).
9. **Site**: update [`apps/site/site.config.json`](site.md#download-links) (see [After publishing](#after-publishing)).

### Building on Windows and macOS

On each machine, with the repository at the release commit (`git fetch --tags && git checkout vX.Y.Z`),
Python 3.11+, uv, Node 24, and the signing environment of [desktop signing](../desktop/releasing.md):

```sh
# macOS (once on Apple silicon and once on Intel, or the Intel row on an Intel Mac)
export BENTO_MAC_SIGNING=1 APPLE_SIGNING_IDENTITY=… APPLE_ID=… APPLE_APP_SPECIFIC_PASSWORD=… APPLE_TEAM_ID=…
export BENTO_TELEGRAM_API_ID=… BENTO_TELEGRAM_API_HASH=… BENTO_RELAY_URL=… BENTO_PUBLIC_SITE_URL=… BENTO_UPDATE_PUBLIC_KEY=…
scripts/release/bento-release build --release --for-import
```

```powershell
# Windows x64 (PowerShell)
$env:BENTO_WINDOWS_SIGNING = "1"; $env:WINDOWS_CERTIFICATE_FILE = "C:\secure\bento.pfx"; $env:WINDOWS_CERTIFICATE_PASSWORD = "…"
$env:BENTO_TELEGRAM_API_ID = "…"; $env:BENTO_TELEGRAM_API_HASH = "…"; $env:BENTO_RELAY_URL = "…"; $env:BENTO_PUBLIC_SITE_URL = "…"; $env:BENTO_UPDATE_PUBLIC_KEY = "…"
py scripts\release\bento-release build --release --for-import
```

On those machines the tool builds `desktop,cli`, checks the clean tree and the signed tag at HEAD and the
production build values, and writes the per-target `SHA256SUMS-<target>` and update manifest. `--for-import`
drops only what belongs to the Linux release machine: the release signing key, the update-manifest key and the
local-CI evidence (local CI ran on Linux for the same commit). Their `SHA256SUMS` stays unsigned; the update
manifests and the final `SHA256SUMS` are signed after `import`. A Linux arm64 machine (for example a Raspberry
Pi) builds `cli-linux-arm64` the same way (`--only cli`).

Before building there, check the signing: macOS `codesign --verify --deep --strict` and
`spctl -a -t exec -vv` on the `.app`, `xcrun stapler validate` on the `.dmg`; Windows
`Get-AuthenticodeSignature` must say `Valid` for `Bento-X.Y.Z-Setup.exe`. A dry run there (`build` without
`--release`) produces unsigned packages and can only be imported into a dry run.

Copy each machine's whole `dist/release/X.Y.Z/` folder to the Linux machine (any transport; `import` checks
every file against that folder's `SHA256SUMS`) and merge it:

```sh
scripts/release/bento-release import ~/incoming/mac-arm64/0.2.0 ~/incoming/mac-x64/0.2.0 ~/incoming/win-x64/0.2.0
```

`import` refuses a folder from another commit, version or mode, a failed component, a file that is not part
of the release, or a file that would replace a different one (`--replace` to accept). It then signs the new
desktop update manifests with `BENTO_UPDATE_SIGNING_KEY_FILE`, rewrites `SHA256SUMS` over every asset and signs
it again, so the merged release has one signed checksum list. `bento-release sign` repeats that last step.

### Publishing

```sh
scripts/release/bento-release publish                  # alias: bento-release --publish
scripts/release/bento-release publish --channel android
scripts/release/bento-release publish --allow-missing cli-linux-arm64     # knowingly ship without a target
```

It refuses dry-run output, a build from another commit or a dirty tree, failed components, a checksum or
signature that does not verify against the committed `allowed_signers`, missing targets (unless listed in
`--allow-missing`), unsigned update manifests, unknown files and unsigned or misplaced tags. Then it asks you to
type the version and, per release:

1. `git push origin refs/tags/<tag>`;
2. `gh release create <tag> --verify-tag --draft --notes-file notes/<tag>.md <assets…>`;
3. compares the draft's asset names and sizes with the local files;
4. publishes the draft: `--latest` for `vX.Y.Z`, `--latest=false` for `android-vX.Y.Z`.

A release that already exists is never modified. If a step fails, inspect the draft on GitHub, delete it if
it is wrong, and run `publish` again; the tag stays.

### After publishing

1. Open both release pages and check the asset list and the notes.
2. Verify from a clean folder as a user: download `SHA256SUMS`, `SHA256SUMS.sig` and one installer and follow
   [verify downloads](../user/en/verify-downloads.md).
3. Point the site buttons at the exact files: in `apps/site/site.config.json` set `release` to the tag and the
   five desktop asset names (`windows-x64`: `Bento-X.Y.Z-Setup.exe`, `macos-arm64`: `Bento-X.Y.Z-arm64.dmg`,
   `macos-x64`: `Bento-X.Y.Z-x64.dmg`, `linux-x64-deb`: the `.deb` name, `linux-x64-zip`:
   `Bento-linux-x64-X.Y.Z.zip`) and `android.release` to the APK names, their SHA-256 values and
   `SHA256SUMS-android-X.Y.Z.txt` ([site](site.md#download-links)). Run `npm test` in `apps/site`, commit and
   deploy. Without this the buttons open the latest release page, which always works.
4. Update `orchestration/execution/status.md` if the program tracks the release.

## GitHub Actions

The workflows in `.github/workflows` are kept but **dormant**: their only trigger is `workflow_dispatch`, so
nothing runs on pushes, pull requests, tags or schedules. They were not deleted because they encode the native
matrix, signing checks and provenance steps that are useful again if billing returns; restore their `on:` blocks
from git history then. `desktop-version-bump.yml` and `apps/desktop/scripts/bump-version.mjs` were removed:
they bumped fewer files than `bento-release version bump` and would leave the manifests inconsistent.
`cli-release.yml` is superseded (`cli-v*` tags are retired). Never dispatch `desktop-release.yml` for a version
released locally.

Branch protection on `main` was removed on 2026-11-24 while Actions is off: changes land as squash-merged pull
requests with the local-CI summary as the gate; see `orchestration/execution/local-integration.md` §6.

## Verifying a release (maintainer)

```sh
scripts/release/bento-release verify ~/Downloads/bento-0.2.0      # folder with SHA256SUMS, .sig and downloads
```

It verifies `SHA256SUMS.sig` against `scripts/release/allowed_signers` and every file in the folder against
`SHA256SUMS`. The user-facing steps are in [verify downloads](../user/en/verify-downloads.md)
([español](../user/es/verificar-descargas.md)).

## Tests

`scripts/release/tests` (stdlib `unittest`, throwaway keys, a fake `gh` and a local bare remote; nothing reaches
GitHub) runs in `scripts/local-ci.sh --light` together with `version check` and `changelog check`:

```sh
cd scripts/release/tests && python3 -m unittest
```
