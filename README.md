![Bento](docs/assets/readme-banner.png)

# Bento

**Tu nube privada, sin límite de espacio, guardada en tu Telegram.**

Bento respalda tus fotos y archivos en tu propia cuenta de Telegram, cifrados antes de salir de tu equipo, y los mantiene en orden en todos tus dispositivos. Sin bots, sin servidores de Bento y sin configurar nada técnico.

> Bento usa la API de Telegram y no está afiliado a Telegram.

_Captura de pantalla: [[COMPLETAR: añadir una captura de la biblioteca en docs/assets/ y mostrarla aquí]]_

## Descargar

Descarga la [última versión](https://github.com/invrnt/bento/releases/latest):

| Sistema | Archivo |
| --- | --- |
| Windows x64 | Instalador firmado `Bento-<versión> Setup.exe` |
| macOS 13 o posterior (Apple silicon o Intel) | `.dmg` firmado y notarizado de tu procesador |
| Ubuntu 22.04 x64 y sistemas basados en Debian | Paquete `.deb` (también hay un `.zip` portátil) |

Comprueba la descarga con el archivo `SHA256SUMS-*` del release: [cómo hacerlo](docs/desktop/install-first-run.md). Todavía no hay app para móvil.

## Cómo funciona

1. **Conecta tu Telegram.** Escanea un QR desde Telegram en tu móvil (Ajustes › Dispositivos › Vincular dispositivo de escritorio). Bento crea en tu cuenta tres canales privados, «Bento · Archivos», «Bento · Sync» y «Bento · Bandeja», dentro de una carpeta «Bento».
2. **Elige qué respaldar.** Imágenes, Documentos, Escritorio u otras carpetas se suben en segundo plano, con reintentos y reanudación.
3. **Guarda tu kit de recuperación.** Con tu Telegram y ese código puedes recuperar todo, aunque pierdas tus equipos.

¿Otro equipo? En Ajustes › Dispositivos › Añadir dispositivo aparece un código como `K7Q2-MXR9-T4WA`: escríbelo en el equipo nuevo, comprueba que los cuatro emojis coinciden en las dos pantallas y confirma. Cada día tienes la Bandeja de Telegram para mandar cosas desde el móvil, envío de copias por Telegram, importación desde Mensajes guardados, papelera de 30 días, vista rápida y búsqueda por el texto de tus fotos y PDF. ¿Prefieres no usar Telegram? Elige «Usar solo en este equipo».

Guías: [español](docs/user/es/README.md) · [English](docs/user/en/README.md).

## Privacidad en resumen

- Todo lo que sale de tu equipo va cifrado con AES-256-GCM: contenido, nombres, carpetas, fechas, ubicación, texto reconocido y la lista de cambios entre equipos.
- Telegram solo ve datos sin contenido: que usas Bento, el tamaño y la hora de las partes cifradas y las sesiones de tus equipos.
- Bento no tiene cuentas ni servidores que guarden tus archivos. El relay de emparejamiento solo pasa mensajes cifrados entre dos equipos durante unos minutos.
- Sin analíticas ni publicidad, y nada se usa para entrenar inteligencia artificial.
- Lo que decides compartir por Telegram sale sin cifrar, y Bento te lo avisa antes.

Más: [Privacidad y seguridad](docs/user/es/privacidad-y-seguridad.md) · [Política de privacidad](docs/legal/es/privacidad.md) · [Términos de uso](docs/legal/es/terminos.md) · [Avisos de terceros](docs/legal/es/avisos-de-terceros.md).

## Límites, sin letra pequeña

- «Sin límite de espacio» significa que Telegram no anuncia hoy un límite total para su nube; no es una garantía contractual. Telegram puede cambiar sus condiciones, limitar la velocidad o restringir cuentas, y elimina las cuentas que pasan demasiado tiempo inactivas.
- Si pierdes todos tus equipos y también el kit de recuperación, nadie puede volver a abrir tu nube.
- Aún no hay app para móvil, enlaces públicos ni nubes compartidas en familia.
- Para lo irreemplazable, conserva también otra copia.

## English

Bento is your private cloud, with no storage limit, kept in your own Telegram account. It encrypts your photos and files on your computer before backing them up, keeps them in order across all your devices, and adds a new computer with a single code. Telegram only sees content-free metadata: that you use Bento, sizes, times and sessions. Telegram does not contractually guarantee unlimited storage, and losing every device **and** the recovery kit means losing access. Bento uses the Telegram API and is not affiliated with Telegram.

Read the [English guides](docs/user/en/README.md), [privacy and security](docs/user/en/privacy-and-security.md) and the [privacy policy](docs/legal/en/privacy.md).

## For developers

Bento is a local-first modular monolith: a FastAPI API and a background worker share one Python package, a React renderer runs in the browser or inside an Electron host, and each device keeps a local SQLite replica. With Telegram storage, the user’s own account (MTProto via Telethon) is both the encrypted blob store and the replication log between devices. Start with the [developer docs](docs/dev/README.md) and the [architecture overview](docs/dev/architecture.md).

### Repository layout

| Path | Purpose |
| --- | --- |
| `apps/api` | Python package `bento` for the API and the worker (domain, application, ports, adapters, infrastructure, interfaces). |
| `apps/web` | React + Vite + TypeScript renderer. |
| `apps/desktop` | Electron host with API/worker sidecars, tray, deep links and signed updates. |
| `apps/relay` | Cloudflare Worker + Durable Object for device pairing ([docs](docs/dev/relay.md)). |
| `apps/site` | Static public website and `/join` page on Cloudflare Pages ([docs](docs/dev/site.md)). |
| `docs` | User guides, legal drafts, desktop and developer docs. |
| `orchestration` | Binding implementation contracts. |

### Runtime processes

- `api`: FastAPI on `127.0.0.1:8000` (desktop: an ephemeral loopback port).
- `worker`: background jobs, sync, backup and inbox import, from the same `bento` package.
- `web`: Vite React app on `127.0.0.1:5173` (packaged into the desktop app).
- `relay` (hosted, optional): only used while pairing devices.
- `site` (hosted): static pages; no backend.

### Quick start

```sh
cp .env.example .env    # Windows: copy .env.example .env
make setup
make doctor
make seed
make up
```

Open the app at `http://127.0.0.1:5173`. The API is available at `http://127.0.0.1:8000/api`.

Backend dependency management uses `uv >=0.11,<0.13`; install or update it before running `make setup`.

```sh
uv self update
```

If `uv` is not installed yet, use the official standalone installer or your package manager.

### Commands

```sh
make setup          # install local deps, create data dirs, run Alembic migrations
make doctor         # validate local mode, DB, writable volumes, compose config, tools
make seed           # add deterministic demo Drive and Photos assets
make test           # backend pytest, frontend Vitest and desktop tests
make pre-commit     # run commit-time hooks against all files
make pre-push       # run push-time project checks against all files
make smoke          # backend release smoke journey
make desktop-make   # native installer/archive makers for the current OS
make desktop-release-artifacts # makers, packaged smoke, SBOM, checksums
make up             # build and start Docker Compose local mode
make watch          # start Docker Compose in watch mode for development
make down
make logs
```

`make watch` syncs source changes into running containers, restarts API/worker on backend changes, and rebuilds services when dependency or Docker build files change.

Backend only:

```sh
cd apps/api && uv run pytest
```

Frontend only:

```sh
npm --prefix apps/web test
```

Relay and site:

```sh
npm --prefix apps/relay test     # Workers runtime tests (vitest-pool-workers)
npm --prefix apps/site test      # build + link, CSP, no-external-request and parser checks
npm --prefix apps/site run preview
```

Install Git hooks locally:

```sh
make pre-commit-install
```

Validate Compose without starting services:

```sh
docker compose config --quiet
```

### Storage backends

| `STORAGE_BACKEND` | What it does | Needs |
| --- | --- | --- |
| `local` (default) | Everything stays on this device. No sync, no pairing. | Nothing. |
| `telegram` | Encrypted vault in three private channels of the user’s Telegram account; multi-device sync and pairing. | `BENTO_TELEGRAM_API_ID` and `BENTO_TELEGRAM_API_HASH` ([how to get them](docs/dev/telegram-credentials.md)). Users sign in with a QR code in the UI. |
| `fake` | Filesystem simulation of the Telegram cloud for development, demos and multi-process tests. Rejected when `ENVIRONMENT=production`. | Optional `BENTO_FAKE_TELEGRAM_DIR` (default `<DATA_DIR>/fake-telegram`). See [multi-device development](docs/dev/multi-device.md). |

### Environment

`.env.example` is safe for local mode:

- `STORAGE_BACKEND=local`
- `WORKER_CONCURRENCY=1`
- `OCR_PROVIDER=disabled`
- `EMBEDDINGS_PROVIDER=disabled`
- `VITE_API_BASE_URL=http://127.0.0.1:8000/api`

Telegram-first configuration:

- `BENTO_TELEGRAM_API_ID`, `BENTO_TELEGRAM_API_HASH`: Bento’s application identity for MTProto. Required for `STORAGE_BACKEND=telegram`.
- `BENTO_RELAY_URL`: pairing relay (`wss://…`). Optional; without it, pairing goes through the user’s Telegram Sync channel.
- `BENTO_PUBLIC_SITE_URL`: public site origin, used for `/join#…` web links in the pairing dialog. Optional.
- `BENTO_FAKE_TELEGRAM_DIR`: shared directory for the `fake` backend.
- `BENTO_DEVICE_WRAPPING_KEY`: headless only. Wraps the local key store (Telegram session, vault keys, device identity). If absent, Bento generates `data/secure/wrapping.key` with mode `0600` and `make doctor` reminds you to protect that folder. The desktop app manages this key itself through the OS secure store.

The bot-based Telegram setup (BotFather, local Bot API server, channel IDs, webhook, `BENTO_ENCRYPTION_KEY`) was removed; see [docs/telegram-setup.md](docs/telegram-setup.md). Docker Compose has no Telegram profile or extra service: with `STORAGE_BACKEND=telegram` and the two credentials in `.env`, sign in from the web UI.

Do not commit API hashes, Telegram sessions, wrapping keys or anything under `data/`.

### Desktop

The packaged Electron app is the recommended path for end users: it includes the web UI plus native API/worker sidecars and requires no Docker, Python, Node or `.env`. See [installation and first run](docs/desktop/install-first-run.md), [settings, backup and recovery](docs/desktop/settings-recovery.md) and [release and signing](docs/desktop/releasing.md).

Stable desktop releases follow GitHub Flow from short-lived `feature/*` or `fix/*` branches into `main`. Maintainers use the manual **Desktop version bump PR** workflow for a stable SemVer `patch`, `minor` or `major`; after the version PR and four-platform native validation pass, an immutable matching `vX.Y.Z` tag builds the signed release. Release tags are blocked unless the Windows installer is signed and both macOS architectures are signed and notarized. Pull requests publish short-lived artifacts whose names include `unsigned`; those are for testing, not distribution.

### Release checks

- `make test`
- `npm --prefix apps/relay test`
- `npm --prefix apps/site test`
- `make doctor`
- `make smoke`
- `docker compose config --quiet`
- Docker Compose local smoke: `make up`, open `http://127.0.0.1:5173`, upload, browse Drive/Photos, search, view Jobs/Settings, then `make down`.

### Brand and design language

Bento’s identity (“Todo en su lugar”), palette, typography, shapes, motion, voice and per-screen patterns are defined in the [brand book](orchestration/design-system/brand.md). The app supports light, dark and system themes; tokens live in `apps/web/src/styles/tokens.css`, and the site mirrors them.

### Known limitations

- OCR and embeddings are disabled in `.env.example`; real providers need local runtime setup and model files. The desktop app turns OCR on automatically on machines with at least 4 cores and 8 GB of RAM, and smart search is an opt-in model download.
- The worker is conservative by default (`WORKER_CONCURRENCY=1`), and Telegram transfers use one upload and one download stream per device unless configured otherwise (maximum 4).
- Telegram may throttle accounts (`FLOOD_WAIT`); Bento waits as instructed. Automated tests never touch real Telegram; they use the `fake` backend.
- Thumbnails and previews depend on worker/media tooling and may be pending until jobs run.
- Not included yet: mobile app, public share links, OS files-on-demand, shared family vaults (specified as deferred in [the product contract](orchestration/product/telegram-first-experience.md)), cloud AI, PostgreSQL or an external vector database.

### Version assumptions

- Python 3.12+ and uv `>=0.11,<0.13`.
- FastAPI `0.115.x`, SQLAlchemy `2.x`, Alembic `1.x`, Uvicorn `0.34.x`, pytest `8.x`.
- Telethon `1.x` (MTProto), cryptography `46.x` (AES-256-GCM, X25519, HKDF), spake2 `0.9.x`, segno `1.x`, websockets, watchdog.
- Node 22, Vite `6.x`, React `19.x`, TypeScript `5.x`, Tailwind CSS `4.x`, Vitest `3.x`.
- Desktop CI/release: Node 24, Python 3.12, Electron `43.4.1`, Electron Forge `7.11.2` and PyInstaller `6.22.2`, built natively rather than cross-compiled.
- Relay: Cloudflare Workers with SQLite-backed Durable Objects (Workers Free plan compatible). Site: Cloudflare Pages, no runtime dependencies, deployed with Wrangler `4.151.3` through `npx`.
- Docker Compose V2 with healthcheck-aware `depends_on` and `develop.watch` support.
