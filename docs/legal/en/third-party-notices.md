# Third-party notices

Español: [Avisos de terceros](../es/avisos-de-terceros.md).

> Draft pending legal review before publishing. See [the legal documents index](../README.md).

## Telegram

Bento uses the Telegram API and is not affiliated with Telegram. Bento is not an official Telegram app and is not endorsed by Telegram. Bento uses its own Telegram API application ID and follows the [Telegram API terms of service](https://core.telegram.org/api/terms).

Telegram is a trademark of its respective owners. The name is used only to say which service Bento works with.

To use Bento’s cloud you need your own Telegram account, subject to Telegram’s [terms of service](https://telegram.org/tos) and [privacy policy](https://telegram.org/privacy).

## Other services

- **Cloudflare** hosts Bento’s website (Cloudflare Pages) and the pairing relay (Cloudflare Workers).
- **GitHub** publishes Bento’s releases and the metadata Bento checks for updates.

## Open-source software

Bento is built with open-source components. This list summarizes the main ones; the complete list for each release, with exact versions and licenses, is in the CycloneDX SBOM (`bento-*.cdx.json`) published with every GitHub release. The full license texts ship with each component.

### Desktop app

| Component | License |
|---|---|
| Electron | MIT |
| Chromium (bundled with Electron) | BSD-3-Clause and other third-party licenses listed by Electron |
| Node.js (bundled with Electron) | MIT |
| PyInstaller (packages the local processes) | GPL-2.0-or-later with a bootloader exception that allows distributing packaged apps |
| Python | PSF-2.0 |

### Local processes (API and background tasks)

| Component | License |
|---|---|
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic, pydantic-settings | MIT |
| python-dotenv | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| SQLAlchemy | MIT |
| Alembic | MIT |
| SQLite | Public domain |
| Telethon | MIT |
| pyaes | MIT |
| rsa | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| spake2 | MIT |
| segno | BSD-3-Clause |
| watchdog | Apache-2.0 |
| websockets | BSD-3-Clause |
| Pillow | MIT-CMU |
| pypdfium2 and PDFium | (Apache-2.0 OR BSD-3-Clause) and PDFium third-party licenses |
| RapidOCR | Apache-2.0 |
| ONNX Runtime | MIT |

### Interface

| Component | License |
|---|---|
| React, React DOM | MIT |
| Radix UI | MIT |
| Tailwind CSS | MIT |
| Lucide (icons) | ISC |
| Geist and Geist Mono (typefaces) | SIL Open Font License 1.1 |

The website includes the Geist and Geist Mono typefaces (SIL Open Font License 1.1, licenses in `apps/site/src/assets/fonts/`) and Lucide icon paths (ISC).

### Smart search

The smart search model is downloaded only if you turn that feature on. Model license: [[COMPLETAR: verificar y citar la licencia del modelo de búsqueda inteligente]].

ffmpeg is not bundled with Bento: if it is installed on your system, Bento uses it to create video thumbnails, under the license of that installation.
