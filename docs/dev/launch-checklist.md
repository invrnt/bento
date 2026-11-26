# Launch checklist (owner actions)

The Telegram-first program is implemented and tested end to end against the simulated Telegram cloud. These steps need the owner's accounts, keys, or decisions and cannot be automated from the repository.

## Required before the first public release

1. **Telegram API credentials** — done: kept in the gitignored root `.env`, which `~/secure/release.env` reads. register Bento at <https://my.telegram.org> (API development tools) and keep `BENTO_TELEGRAM_API_ID` / `BENTO_TELEGRAM_API_HASH` in the local [release environment](releasing.md#release-environment) (GitHub Actions does not run). See [telegram-credentials.md](telegram-credentials.md). Without them, sign-in reports `telegram_not_available`.
2. **Real-account smoke test** — with the credentials in your local env, run Bento with `STORAGE_BACKEND=telegram` against a secondary Telegram account: QR sign-in, vault creation, upload/download of a large video (> 512 MiB to exercise parts), streaming, a second device by code, removal, recovery. The fake cloud mirrors Telegram's behaviour but cannot prove flood limits, file-reference refresh, or `auth.acceptLoginToken` restrictions on real servers.
3. **Pairing relay** — done: deployed; its URL is in the root `.env`. `cd apps/relay && npx wrangler login && npm run deploy` (Workers Free plan is enough; check `ratelimits[0].namespace_id` is unique in the account), then set `BENTO_RELAY_URL=wss://bento-relay.<subdomain>.workers.dev` in the release environment. See [relay.md](relay.md). Redeploy after relay changes.
4. **Update signing key** — done: `~/bento-update-signing.pem`, wired into `~/secure/release.env`; keep the offline backup. `npm --prefix apps/desktop run release:sign-manifest -- --generate-key ~/bento-update-signing.pem`; point `BENTO_UPDATE_SIGNING_KEY_FILE` at the PEM and set `BENTO_UPDATE_PUBLIC_KEY` to the printed public key in the release environment; keep an offline encrypted backup. See [../desktop/releasing.md](../desktop/releasing.md).
5. **Legal review** — done for the public site: the privacy, terms and security pages in `apps/site` are final (Humans Corporation S.A.S.) and deployed; `docs/legal/**` only links to them. Still recommended: a lawyer reviews them, and a decision on whether the smart-search model’s CC BY-NC 4.0 license matters for you (see `docs/legal/en/third-party-notices.md`).
6. **Telegram API terms** — confirm with counsel the reading applied in the product: data obtained from Telegram (Inbox, imports) is never sent to OCR/embeddings (§1.5); Bento discloses that it uses the Telegram API and is not affiliated with Telegram (§2.2–2.3); automatic Inbox reactions are documented to users (§1.4).
7. **Public site** — done (2026-11-25): deployed to https://bentocloud.app. `npm --prefix apps/site run deploy` after the legal review, add the custom domain, then set `BENTO_PUBLIC_SITE_URL`. See [site.md](site.md).
8. **License** — done: AGPL-3.0-only (`LICENSE`).
9. **Android signing keystore** — done (2026-11-25): `~/secure/bento-android-release.jks`, alias `bento`, passphrase-protected; its SHA-256 is in `apps/site/site.config.json` and `~/secure/release.env`. Keep an offline backup. generate the release keystore once (`keytool -genkeypair … -storetype PKCS12 -keyalg RSA -keysize 4096`), keep it and its passwords offline and in a password manager (losing it breaks updates for every user), pin its SHA-256 as `BENTO_ANDROID_CERT_SHA256` and publish it in `/.well-known/assetlinks.json`. Android releases are built and signed locally with `apps/android/scripts/release.sh`, which signs the Android update-manifest entries with the same key as step 4. See [android-release.md](android-release.md).
10. **Release signing key** — done (2026-11-25): `~/.ssh/bento_release_ed25519` (passphrase-protected) is in `scripts/release/allowed_signers` and local git signs tags with it. Remaining: register `~/.ssh/bento_release_ed25519.pub` on GitHub as an SSH *signing* key so tags show as Verified. create the SSH key that signs every release's `SHA256SUMS`, add its public line to `scripts/release/allowed_signers` (replacing the `[[COMPLETAR]]` line), register it on GitHub as a signing key and configure `git tag -s` with it. See [releasing.md](releasing.md#keys).
11. **Release machine tools** — `dpkg` and `fakeroot` are installed. Still needed: access to a Windows x64 machine and macOS machines (Apple silicon and Intel) with the code-signing certificates, because those packages cannot be built on Linux. See [releasing.md](releasing.md#building-on-windows-and-macos).
12. **Branch protection** — done: removed on 2026-11-24; squash-merged PRs with the local-CI summary are the gate (`orchestration/execution/local-integration.md` §6).
13. **Code of Conduct contact** — done: `conduct@bentocloud.app` (Cloudflare Email Routing forwards it to the owner), and private vulnerability reporting is enabled.

## Recommended

- Publish installers also under version-free names so the site can link straight to the latest files.
- Run `make e2e` (multi-process journeys, ~2–3 min) before every release in addition to `make test`.
- Plan an external security audit of the crypto and pairing protocols before 1.0 (see the residual risks in `orchestration/execution/telegram-first-program.md`).

## Deferred features (specified, not built)

An iPhone app, files on demand in the OS file manager, public links for non-Telegram recipients, and shared family vaults are specified in `orchestration/product/telegram-first-experience.md` § Deferred and need their own programs.
