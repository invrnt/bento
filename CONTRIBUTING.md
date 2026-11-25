# Contributing to Bento

Thank you for helping. Bento is a local-first private cloud: your files stay on your devices and travel,
end-to-end encrypted, through your own Telegram account. Contributions of every size are welcome: bug
reports, translations, documentation, tests and code.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) first. Security problems are **not** reported in public
issues: follow [SECURITY.md](SECURITY.md).

## Before you start

- For a bug, open an issue with the bug form. For a feature or a larger change, open a feature request first
  and wait for agreement on the approach: it saves you from a pull request that cannot be merged.
- Read [`AGENTS.md`](AGENTS.md) (the rules every change follows, human or AI agent) and the
  [architecture overview](docs/dev/architecture.md). The binding contracts live in
  [`orchestration/`](orchestration/README.md).
- A few rules matter in every change:
  - Clean architecture: `interfaces -> application -> domain`; external systems only behind ports and adapters;
    no business rules in FastAPI endpoints or React components.
  - Everything that leaves the device (Telegram, the relay) is end-to-end encrypted. Never log secrets,
    Telegram sessions, login or pairing codes, recovery kits or keys.
  - User-facing text goes through the i18n dictionaries. Spanish is the default locale; add the English
    string in the same change.
  - No new framework, state library, ORM, queue or design system without updating the orchestration docs first.

## Development setup

| Component | Path | Guide |
|---|---|---|
| Backend API and worker (Python, uv) | `apps/api` | [README › For developers](README.md#for-developers) |
| Web UI (React + Vite) | `apps/web` | [README › Quick start](README.md#quick-start) |
| Desktop app (Electron) | `apps/desktop` | [README › Desktop](README.md#desktop), [desktop release](docs/desktop/releasing.md) |
| `bento` CLI | `apps/api/src/bento/interfaces/cli` | [docs/dev/cli.md](docs/dev/cli.md) |
| Android app (Kotlin, Compose) | `apps/android` | [docs/dev/android.md](docs/dev/android.md) |
| Pairing relay (Cloudflare Workers) | `apps/relay` | [docs/dev/relay.md](docs/dev/relay.md) |
| Public site | `apps/site` | [docs/dev/site.md](docs/dev/site.md) |
| Several devices on one machine | — | [docs/dev/multi-device.md](docs/dev/multi-device.md) |
| Telegram API credentials | — | [docs/dev/telegram-credentials.md](docs/dev/telegram-credentials.md) |

All guides are indexed in [docs/dev](docs/dev/README.md). The fake Telegram cloud lets you develop and test
without a real account; never use someone else's account or real data in tests.

## The local CI gate

GitHub Actions does not run for this repository. The gate is [`scripts/local-ci.sh`](scripts/local-ci.sh)
([how it works](orchestration/execution/local-integration.md)); run it on your branch before asking for review:

```sh
scripts/local-ci.sh --light                    # backend, web, desktop, site, relay, release tooling
scripts/local-ci.sh --auto main                # only the components your branch touches
scripts/local-ci.sh --merge                    # light + fast Android checks (JDK 17, Android SDK)
```

Paste the printed summary into the pull request. Maintainers run the full gate (`--full`, with Android
journeys on the emulator) and record it in `orchestration/execution/evidence/local-ci.md` before merging.
Write tests in the same change as the code: domain and application tests must not need SQLite, Telegram, OCR,
embeddings, ffmpeg or Docker.

## Commits and pull requests

- Branch from `main` as `feature/<topic>` or `fix/<topic>`; keep pull requests focused (one concern each).
- Commit messages: a short imperative subject (≤ 72 characters) that names the area, for example
  `Android: keep the viewer position after rotation`, and a body explaining why when it is not obvious.
- Every commit carries a **Developer Certificate of Origin** sign-off (see below).
- Add a line to [`CHANGELOG.md`](CHANGELOG.md) under `## [Unreleased]` for any user-visible change.
- Update the docs (user guides in Spanish and English, developer guides) when behavior changes.
- Pull requests are squash-merged into `main` with linear history once the gate is green and a maintainer
  has approved.
- Do not bump the version or touch `VERSION`; releases are cut by maintainers
  ([releasing](docs/dev/releasing.md)).

## License and sign-off

Bento is licensed under the [GNU Affero General Public License v3.0 only](LICENSE) (`AGPL-3.0-only`). By
contributing you agree that your contribution is licensed under the same license ("inbound = outbound"); there is
no separate contributor license agreement and you keep the copyright of your work.

Instead of a CLA we use the [Developer Certificate of Origin 1.1](https://developercertificate.org/): by adding a
`Signed-off-by` line you certify that you wrote the change or otherwise have the right to submit it under the
project's license. Sign off every commit with `git commit -s`, which adds:

```text
Signed-off-by: Your Name <you@example.com>
```

Use your real name or the name you are publicly known by, and an email you can be reached at. To sign off a
branch after the fact: `git rebase --signoff main`. Do not submit code you cannot license under AGPL-3.0 (for
example code copied from projects with incompatible licenses); third-party code needs its license recorded in
[third-party notices](docs/legal/en/third-party-notices.md).

## AI-assisted contributions

Agents and AI tools are welcome; they follow `AGENTS.md` like everyone else. You remain responsible for every
line you submit: review it, test it and sign it off yourself.
