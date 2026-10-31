# Launch checklist (owner actions)

The Telegram-first program is implemented and tested end to end against the simulated Telegram cloud. These steps need the owner's accounts, keys, or decisions and cannot be automated from the repository.

## Required before the first public release

1. **Telegram API credentials** — register Bento at <https://my.telegram.org> (API development tools) and store `BENTO_TELEGRAM_API_ID` / `BENTO_TELEGRAM_API_HASH` as GitHub Actions secrets. See [telegram-credentials.md](telegram-credentials.md). Without them, sign-in reports `telegram_not_available`.
2. **Real-account smoke test** — with the credentials in your local env, run Bento with `STORAGE_BACKEND=telegram` against a secondary Telegram account: QR sign-in, vault creation, upload/download of a large video (> 512 MiB to exercise parts), streaming, a second device by code, removal, recovery. The fake cloud mirrors Telegram's behaviour but cannot prove flood limits, file-reference refresh, or `auth.acceptLoginToken` restrictions on real servers.
3. **Pairing relay** — `cd apps/relay && npx wrangler login && npm run deploy` (Workers Free plan is enough; check `ratelimits[0].namespace_id` is unique in the account), then set the GitHub variable `BENTO_RELAY_URL=wss://bento-relay.<subdomain>.workers.dev`. See [relay.md](relay.md). Redeploy after relay changes.
4. **Update signing key** — `npm --prefix apps/desktop run release:sign-manifest -- --generate-key ~/bento-update-signing.pem`; add the PEM as secret `BENTO_UPDATE_SIGNING_KEY` and the printed public key as variable `BENTO_UPDATE_PUBLIC_KEY`; keep an offline encrypted backup. See [../desktop/releasing.md](../desktop/releasing.md).
5. **Legal review** — fill every `[[COMPLETAR: …]]` placeholder (entity, contact and privacy emails, effective date, license and price, jurisdiction, retention periods) in `docs/legal/**`, `apps/site/**`, and the README, and have a lawyer review the privacy policy and terms. The site's deploy guard refuses to publish while placeholders remain.
6. **Telegram API terms** — confirm with counsel the reading applied in the product: data obtained from Telegram (Inbox, imports) is never sent to OCR/embeddings (§1.5); Bento discloses that it uses the Telegram API and is not affiliated with Telegram (§2.2–2.3); automatic Inbox reactions are documented to users (§1.4).
7. **Public site** — `npm --prefix apps/site run deploy` after the legal review, add the custom domain, then set `BENTO_PUBLIC_SITE_URL`. See [site.md](site.md).
8. **License** — `apps/desktop/package.json` is `UNLICENSED`; choose the project license.

## Recommended

- Publish installers also under version-free names so the site can link straight to the latest files.
- Run `make e2e` (multi-process journeys, ~2–3 min) before every release in addition to `make test`.
- Plan an external security audit of the crypto and pairing protocols before 1.0 (see the residual risks in `orchestration/execution/telegram-first-program.md`).

## Deferred features (specified, not built)

Mobile app with camera-roll backup, files on demand in the OS file manager, public links for non-Telegram recipients, and shared family vaults are specified in `orchestration/product/telegram-first-experience.md` § Deferred and need their own programs.
