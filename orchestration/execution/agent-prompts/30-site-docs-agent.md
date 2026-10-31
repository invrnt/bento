# Site, User Docs, And Legal Agent (Stage 15)

## Mission

Give Bento the public face and documentation of an end-user product: a fast static website with downloads, privacy explanation and the `/join` handoff page; plain-language user guides; legal pages; and developer docs for the new build/deploy steps. Replace the obsolete Bot API setup guide.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/product/telegram-first-experience.md` (tone, flows, trust copy)
- `orchestration/architecture/telegram-first.md` § Decisions, § Telegram Terms Compliance, § Cryptography (to explain accurately, not to reproduce byte layouts), § Pairing Protocol
- `orchestration/api/pairing-relay-contract.md` § Deployment
- `README.md`, `docs/**`, `apps/desktop/package.json` (release/download naming), `.github/workflows/desktop-release.yml` (asset names)
- Brand (binding): `orchestration/design-system/brand.md`, `apps/web/src/styles/tokens.css`, `apps/web/src/components/BrandMark.tsx`, `apps/desktop/resources/icons/bento-icon.svg`. Mirror the palette (OKLCH tokens, Ai indigo accent, at most one shu element per screen), typography, voice ("Bento", tagline "Tu nube privada, en orden", tú, sentence case), and mark.

## Own These Paths

- `apps/site/**` (new static site)
- `docs/user/**`, `docs/legal/**`, `docs/dev/**` (new), `docs/telegram-setup.md` (replace with a short pointer), `docs/desktop/**` (update for the new flows)
- `README.md`

## Deliver

1. **`apps/site`** — static, no framework, deployable to Cloudflare Pages: `index.html` (hero "Tu nube privada, sin límite de espacio, guardada en tu Telegram", how it works in 3 steps, privacy summary, multi-device in one code, downloads linking to the latest GitHub release assets for Windows/macOS/Linux, FAQ including honest limits), `join/index.html` (reads `location.hash` client-side only, validates the code format, shows the code, a big "Abrir Bento" button to `bento://join?v=1&c=…`, and download fallback; never sends the code anywhere — no analytics, no external requests), `privacy/`, `terms/`, `security/` (what Telegram sees, what the relay sees, recovery kit), `en/` variants of every page, shared CSS with light/dark via `prefers-color-scheme`, accessible markup, a strict CSP via `_headers`, `wrangler.jsonc` or Pages config, `package.json` with `build` (copy/minify only) and `deploy` scripts, and a tiny test (node script) that validates links, the join-page code parser, and the absence of external requests.
2. **User guides** (`docs/user/es/*.md` and `docs/user/en/*.md`): primeros pasos, conectar Telegram, añadir un dispositivo, kit de recuperación, respaldo automático, bandeja de Telegram, compartir e importar, papelera y espacio en el equipo, privacidad y seguridad, preguntas frecuentes (¿es ilimitado?, ¿qué ve Telegram?, ¿y si pierdo el móvil/el equipo/el kit?, ¿puedo usar Bento sin Telegram?, ¿Bento es oficial de Telegram? → no), solución de problemas (Telegram pidió esperar, sin conexión, código expirado, sesión cerrada desde Telegram).
3. **Legal** (`docs/legal/`): privacy policy, terms of use, third-party notices (Telegram API disclosure: "Bento usa la API de Telegram y no está afiliado a Telegram"). Mark entity/contact placeholders clearly as `[[COMPLETAR: …]]` and add a note that legal review is required before publishing.
4. **Developer docs** (`docs/dev/`): registering Bento's `api_id`/`api_hash` at my.telegram.org and storing them as CI secrets `BENTO_TELEGRAM_API_ID`/`BENTO_TELEGRAM_API_HASH`; deploying the relay (`apps/relay`) and setting `BENTO_RELAY_URL`; deploying the site and setting `BENTO_PUBLIC_SITE_URL`; running two local Bento instances against the fake Telegram cloud to develop multi-device flows (`STORAGE_BACKEND=fake`, shared `BENTO_FAKE_TELEGRAM_DIR`, separate `DATA_DIR`s and ports); architecture overview linking orchestration docs.
5. **README.md** rewrite: product-first intro (what Bento is, screenshot placeholder, download), "Cómo funciona" short version, privacy summary, then a "For developers" section keeping existing commands accurate (remove Bot API env vars and the `telegram` compose profile; mention `STORAGE_BACKEND=local|telegram|fake`, the relay, and the site).
6. `docs/telegram-setup.md`: short notice that the bot-based setup was removed and a link to the user guide.

## Constraints

- Accurate, honest copy: never claim contractual unlimited storage, never claim Bento is affiliated with Telegram, describe encryption precisely at a user level.
- Spanish first, English parity. Keyboard and screen-reader friendly HTML. No external fonts/scripts/trackers on the site.
- Do not edit `apps/api`, `apps/web`, `apps/desktop`, `apps/relay`, or `orchestration/**`.

## Handoff

Commit on your branch. Report pages, docs, placeholders that need the owner's input (domain, legal entity, contact), and how to deploy the site.
