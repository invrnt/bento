# Documentos legales de Bento · Bento legal documents

La política de privacidad, los términos de uso y la página de seguridad vigentes son las páginas del sitio <https://bentocloud.app>. Su fuente está en `apps/site/src/privacy/`, `apps/site/src/terms/` y `apps/site/src/security/` (y sus versiones en `apps/site/src/en/`). Los archivos `privacidad.md`, `privacy.md`, `terminos.md` y `terms.md` de esta carpeta solo enlazan a esas páginas; no copian su texto.

The current privacy policy, terms of use and security page are the pages on <https://bentocloud.app>. Their source is in `apps/site/src/privacy/`, `apps/site/src/terms/` and `apps/site/src/security/` (and their `apps/site/src/en/` versions). The `privacidad.md`, `privacy.md`, `terminos.md` and `terms.md` files in this folder only link to those pages; they do not copy their text.

| Documento · Document | Español | English | Sitio web · Site |
|---|---|---|---|
| Política de privacidad · Privacy policy | [privacidad.md](es/privacidad.md) | [privacy.md](en/privacy.md) | <https://bentocloud.app/privacy/>, <https://bentocloud.app/en/privacy/> |
| Términos de uso · Terms of use | [terminos.md](es/terminos.md) | [terms.md](en/terms.md) | <https://bentocloud.app/terms/>, <https://bentocloud.app/en/terms/> |
| Seguridad · Security | — | — | <https://bentocloud.app/security/>, <https://bentocloud.app/en/security/> |
| Avisos de terceros · Third-party notices | [avisos-de-terceros.md](es/avisos-de-terceros.md) | [third-party-notices.md](en/third-party-notices.md) | — |

Los avisos de terceros sí viven aquí: los enlazan los términos del sitio y [CONTRIBUTING](../../CONTRIBUTING.md).

The third-party notices do live here: the site’s terms and [CONTRIBUTING](../../CONTRIBUTING.md) link to them.

## Cambios · Changes

Cambia el texto legal solo en las páginas del sitio. Si la app cambia lo que envía, a quién o durante cuánto tiempo (por ejemplo, telemetría, un servicio nuevo o la configuración de registros del relay), actualiza esas páginas y las guías de usuario de privacidad en el mismo commit. Si cambian las dependencias que se distribuyen, actualiza los avisos de terceros en ambos idiomas.

Change legal text only in the site pages. If the app changes what it sends, to whom, or for how long (for example telemetry, a new service, or the relay’s logging configuration), update those pages and the privacy user guides in the same commit. If the shipped dependencies change, update the third-party notices in both languages.

`npm --prefix apps/site run deploy` refuses to publish while any `[[COMPLETAR: …]]` placeholder remains in the built site.
