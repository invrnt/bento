# Documentos legales de Bento · Bento legal documents

> **Revisión legal obligatoria antes de publicar.** Estos textos son borradores redactados para describir con precisión cómo funciona Bento. Un profesional debe revisarlos y adaptarlos a la ley aplicable antes de publicarlos.
>
> **Legal review is required before publishing.** These texts are drafts written to describe accurately how Bento works. A professional must review them and adapt them to the applicable law before they are published.

| Documento | Español | English | Sitio web |
|---|---|---|---|
| Política de privacidad · Privacy policy | [privacidad.md](es/privacidad.md) | [privacy.md](en/privacy.md) | `/privacy/`, `/en/privacy/` |
| Términos de uso · Terms of use | [terminos.md](es/terminos.md) | [terms.md](en/terms.md) | `/terms/`, `/en/terms/` |
| Avisos de terceros · Third-party notices | [avisos-de-terceros.md](es/avisos-de-terceros.md) | [third-party-notices.md](en/third-party-notices.md) | — |

## Datos que debe completar el responsable · Owner placeholders

Todos los datos pendientes están marcados como `[[COMPLETAR: …]]`, con el mismo texto en ambos idiomas, en estos documentos y en las páginas del sitio (`apps/site/src/privacy/`, `apps/site/src/terms/`, `apps/site/src/security/` y sus versiones en `en/`). `npm --prefix apps/site run deploy` se niega a publicar mientras quede alguno.

Every pending value is marked `[[COMPLETAR: …]]`, with the same text in both languages, in these documents and in the site pages. `npm --prefix apps/site run deploy` refuses to publish while any remains. Find them with:

```sh
grep -rn "\[\[COMPLETAR" docs apps/site/src README.md
```

- Nombre legal, domicilio y correos de contacto (general, privacidad y seguridad).
- Fecha de entrada en vigor.
- Licencia del software y precio, si lo hay.
- Ley aplicable, tribunales competentes y autoridad de protección de datos.
- Bases jurídicas, garantías para transferencias internacionales y plazo de conservación de los registros del relay.
- Origen y licencia del modelo de búsqueda inteligente.
- Retirar el aviso de borrador de las páginas de privacidad y términos tras la revisión.

## Mantener el sitio y los documentos alineados · Keeping the site and these files in sync

Las páginas de privacidad y términos del sitio y estos archivos contienen el mismo texto. Cuando cambies uno, cambia el otro en el mismo commit. Si la app cambia lo que envía, a quién o durante cuánto tiempo (por ejemplo, telemetría, un servicio nuevo o la configuración de registros del relay), actualiza primero estos textos.

The privacy and terms pages on the site and these files carry the same text. When you change one, change the other in the same commit. If the app changes what it sends, to whom, or for how long (for example telemetry, a new service, or the relay’s logging configuration), update these texts first.
