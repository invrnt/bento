# Bento — Marca y lenguaje de diseño

> **Todo en su lugar.** Tu nube privada, ordenada como una caja bento.

Este documento es la fuente de verdad de la identidad visual y verbal de Bento. Los tokens viven en `apps/web/src/styles/tokens.css`; los primitivos en `apps/web/src/components`. Si algo de la UI contradice este documento, el documento manda (o se actualiza primero).

---

## 1. Esencia

Una caja bento es la idea de orden más bella que existe para lo cotidiano: un recipiente cerrado, compartimentos de distintos tamaños, cada cosa en su sitio y espacio de sobra entre ellas. Bento hace lo mismo con fotos, archivos y documentos: los guarda **en tu equipo**, los ordena y los encuentra.

| Valor | Qué significa en la UI |
| --- | --- |
| **Privado** | Nada sale del equipo sin que el usuario lo decida. Los estados de almacenamiento y los secretos se comunican con calma y precisión, nunca con alarma. |
| **Ordenado** | Compartimentos claros, jerarquía obvia, una acción principal por zona. |
| **Sereno** | Pocos colores, mucho espacio (*ma*), movimiento corto. El trabajo pesado (OCR, embeddings, miniaturas) ocurre en segundo plano y nunca bloquea. |
| **Artesanal** | Detalles cuidados: radios anidados, sombras teñidas, tipografía precisa, textos bien escritos. |

**Promesa:** abrir Bento debe sentirse como abrir una caja bien hecha: todo está donde esperas.

---

## 2. Nombre y voz

- **Nombre:** *Bento*, siempre con B mayúscula y sin artículo ("Bento guarda…", no "el Bento"). La app de escritorio es *Bento Desktop* solo cuando hay que distinguirla del modo navegador.
- **Tagline:** "Tu nube privada, en orden".
- **Idioma por defecto:** español, tuteo. Todo texto pasa por `src/i18n/dictionary.ts`.

### Tono

| Sí | No |
| --- | --- |
| Claro y breve: "Sube archivos o crea carpetas." | Técnico sin necesidad: "Ejecuta el pipeline de ingesta." |
| Verbos concretos en botones: "Subir archivos", "Crear álbum", "Liberar espacio". | Botones genéricos: "OK", "Aceptar", "Enviar". |
| Tranquilo ante errores: "No se pudo completar la acción. Inténtalo otra vez." | Culpar o alarmar: "¡Error fatal!" |
| Explicar consecuencias antes de acciones destructivas. | Confirmaciones vacías: "¿Estás seguro?" |

### Reglas de escritura

- Ortografía completa: tildes, `¿?` y `¡!`. ("Álbumes", "Búsqueda", "Navegación").
- Mayúscula solo al inicio (*sentence case*): "Nueva carpeta", no "Nueva Carpeta".
- Puntos suspensivos tipográficos (`…`) para estados en curso: "Subiendo…", "Aplicando…".
- Números con formato local (`Intl`, locale `es`): `1,5 KB`, `42,5 %`.
- Términos técnicos (OCR, embeddings) solo donde el usuario configura esas capacidades; en el resto se habla de "texto en imágenes" y "búsqueda por significado".

---

## 3. Logo

La marca es una **caja lacada con tres compartimentos** y un único punto bermellón: el *umeboshi* del *hinomaru bento*, la ciruela que corona el arroz. Es el elemento más reconocible de la identidad y la razón de la regla "una sola ume por pantalla" (ver §4).

```
┌───────────────┐   viewBox 32×32, radio exterior 9
│ ┌───┐ ┌─────┐ │   compartimento alto: 10,5×22 (x 4,5 · y 5)
│ │   │ │     │ │   compartimentos derechos: 10,5×10 (x 17 · y 5 / y 17), separación 2
│ │   │ └─────┘ │   radio interior 3,5 (anidado: 9 − margen)
│ │   │ ┌─────┐ │   ume: círculo r 2,75 en (22,25 · 22)
│ │   │ │  ●  │ │
│ └───┘ └─────┘ │
└───────────────┘
```

- **Componente:** `BrandMark` (solo símbolo) y `BrandLogo` (símbolo + palabra "Bento" en Geist 600, tracking −0,03 em).
- **Color:** caja en `ink`, compartimentos en `tray`, ume en `shu`. En modo oscuro se invierte solo, porque usa tokens.
- **Área de respeto:** 25 % del lado del símbolo alrededor.
- **Tamaño mínimo:** 16 px (favicon). Por debajo de 24 px no se acompaña de la palabra.
- **Archivos:** `apps/web/public/favicon.svg` y `apps/desktop/resources/icons/bento-icon.svg` (fuente de los íconos `.png/.ico/.icns`, generados con `npm run icons:generate`).
- **No:** rotar, cambiar proporciones, usar degradados o sombras en el símbolo, poner más de un punto, cambiar el color del ume.

`BentoLoader` es la versión animada: los compartimentos se llenan uno tras otro y el ume aparece al final. Es el único indicador de carga de página.

---

## 4. Color

Todo color se define en OKLCH con `light-dark()` y se cambia con `color-scheme` en `<html>`. **La paleta por defecto de Tailwind está desactivada**: en componentes solo existen los tokens de abajo (`bg-surface`, `text-ink-muted`, `border-line`…). Nunca se escribe un hex, `slate-*`, `teal-*`, etc.

### 4.1 Neutros: washi de día, índigo de noche

De día la bandeja es papel *washi* cálido; de noche, tela teñida de índigo.

| Token | Uso | Claro | Oscuro |
| --- | --- | --- | --- |
| `tray` | Bandeja: fondo de la app y de la barra lateral | `#f5f2ee` | `#0c0e15` |
| `surface` | Compartimento principal (panel de contenido) | `#fdfdfb` | `#13161d` |
| `raised` | Tarjetas, menús, diálogos, campos | `#ffffff` | `#1b1e26` |
| `subtle` | Fondos suaves, pies de diálogo, cabeceras de tabla | `#f7f5f2` | `#191c23` |
| `sunken` | Pozos: miniaturas vacías, pistas de controles | `#efece8` | `#0e1017` |
| `hover` / `pressed` | Capas translúcidas de interacción | tinta 5,5 % / 9 % | blanco 6 % / 10 % |
| `line` / `line-strong` | Bordes finos / bordes con énfasis | `#e2dfdb` / `#d4d0ca` | `#272a32` / `#363a44` |
| `ink` | Texto principal (*sumi*) | `#221d18` | `#eff0f4` |
| `ink-muted` | Texto secundario (≥ 5,6:1) | `#655f59` | `#a5a9b2` |
| `ink-subtle` | Placeholders, metadatos, íconos inactivos | `#7f7973` | `#7c808a` |

### 4.2 Ai (índigo): el color de la interacción

`accent` significa "puedes actuar aquí" o "estás aquí": botón primario, foco, selección, navegación activa, progreso, enlaces.

| Token | Claro | Oscuro |
| --- | --- | --- |
| `accent` (fondo de botón primario; texto blanco ≥ 4,9:1) | `#3857d8` | `#4466e0` |
| `accent-hover` | `#2c47c7` | `#5074f0` |
| `accent-soft` (selección, fondos activos) | `#e6eeff` | `#1f2b51` |
| `accent-ink` (texto/ícono de acento) | `#2f4bc3` | `#9fbbff` |
| `focus` (anillo de foco) | `#4366e8` | `#7c9fff` |

### 4.3 Shu (bermellón): la chispa

`shu` es el ume. **Regla de oro: como máximo un elemento shu visible por pantalla.** Se reserva para:

- el punto del logo,
- el corazón de favorito (lo que atesoras),
- la marca de "recomendado" en el primer inicio.

Nunca para botones, errores ni texto largo.

| Token | Claro | Oscuro |
| --- | --- | --- |
| `shu` | `#e94f13` | `#f86f3c` |
| `shu-soft` / `shu-ink` | `#ffeae0` / `#c03809` | `#4a1f12` / `#fd9a73` |

### 4.4 Semánticos

Cada tono tiene tres pasos: color pleno (puntos, íconos, barras), `-soft` (fondo de insignias y avisos) e `-ink` (texto sobre `-soft`, ≥ 5,5:1).

| Tono | Nombre | Uso | Pleno claro / oscuro |
| --- | --- | --- | --- |
| `success` | Matcha | Indexado, guardado, conectado | `#26894c` / `#54c57a` |
| `warning` | Kohaku (ámbar) | En proceso, pendiente, atención | `#dd9314` / `#f3b94c` |
| `danger` | Beni (carmín) | Fallo, acción destructiva | `#d22d33` / `#d53c3d` |
| `info` | Ai | Avisos informativos (usa `accent`) | — |

El color nunca es la única señal: siempre va con ícono o texto.

### 4.5 Paleta de compartimentos

Los tipos de archivo usan un color "alimento" cada uno, siempre como ícono `kind-*` sobre fondo `kind-*-soft`:

| Tipo | Token | Inspiración |
| --- | --- | --- |
| Carpeta | `kind-folder` | Tamago (huevo) |
| PDF | `kind-pdf` | Beni |
| Documento | `kind-doc` | Ai |
| Hoja de cálculo | `kind-sheet` | Matcha |
| Presentación | `kind-slides` | Shu |
| Imagen | `kind-image` | Ume (ciruela) |
| Video | `kind-video` | Sora (cielo) |
| Audio | `kind-audio` | Sakura |
| Comprimido | `kind-archive` | Kinako |
| Texto / otro | `kind-text` | Sumi |

---

## 5. Tipografía

- **Familia:** Geist Variable (UI) y Geist Mono Variable (IDs, rutas, tamaños, atajos, código). Empaquetadas con `@fontsource-variable` porque el CSP del escritorio solo permite fuentes locales.
- **Base:** 14 px. Interlineado generoso; `text-wrap: balance` en títulos y `pretty` en párrafos.
- **Tracking:** 0 en texto; `tight` (−0,012 em) en títulos de sección; `tighter` (−0,022 em) en títulos de página.
- **Pesos:** 400 texto, 500 controles y etiquetas, 600 títulos. Nunca 700+ salvo cifras grandes.
- **Cifras:** `tabular-nums` en tablas, contadores y porcentajes.

| Token | Tamaño / interlineado | Uso |
| --- | --- | --- |
| `text-2xs` | 11 / 16 | Insignias |
| `text-xs` | 12 / 16 | Metadatos, ayudas |
| `text-sm` | 13 / 20 | Etiquetas de campo, controles densos |
| `text-base` | 14 / 22 | Texto y controles |
| `text-md` | 15 / 24 | Botones grandes |
| `text-lg` | 17 / 24 | Títulos de sección, diálogos |
| `text-xl` | 20 / 28 | Títulos de grupo (meses en Fotos) |
| `text-2xl` | 24 / 32 | Título de página (`PageHeader`) |
| `text-3xl` | 32 / 38 | Cifras destacadas (Trabajos) |

No se escala el texto con el ancho de la ventana.

---

## 6. Forma

### Compartimentos y *ma*

La UI es una **bandeja** (`tray`) que sostiene **compartimentos**. Entre compartimentos siempre hay espacio visible (*ma*): 8 px en el shell, 12–24 px dentro de las páginas. No se apilan compartimentos sin aire entre ellos y **no se anidan tarjetas dentro de tarjetas**.

### Radios anidados

Regla: **radio exterior = radio interior + separación**. Así las curvas son concéntricas, como en una caja lacada.

| Token | Valor | Uso |
| --- | --- | --- |
| `rounded-xs` | 6 px | Insignias cuadradas, kbd, checkbox interno |
| `rounded-sm` | 8 px | Controles densos (32 px), ítems de menú |
| `rounded-md` | 10 px | Botones y campos (36 px), navegación |
| `rounded-lg` | 14 px | Tarjetas, menús, avisos |
| `rounded-xl` | 18 px | Compartimento principal, diálogos, miniaturas grandes |
| `rounded-2xl` | 24 px | Superficies hero (primer inicio) |
| `rounded-full` | — | Insignias de estado, píldoras, avatares |

### Espaciado

Unidad base 4 px. Separaciones habituales: 8, 12, 16, 24, 32. Alturas de control: 32 (denso), 36 (estándar), 44 (destacado).

---

## 7. Elevación

Bordes finos primero; sombras solo para indicar capas. Las sombras están teñidas de tinta (nunca negro puro en claro) y son suaves.

| Token | Uso |
| --- | --- |
| `shadow-xs` | Campos, botones secundarios, tarjetas en reposo |
| `shadow-sm` | Compartimento principal, ítem de navegación activo, segmento activo |
| `shadow-md` | Tarjetas al pasar el cursor, tooltips |
| `shadow-lg` | Menús, popovers, barras flotantes |
| `shadow-xl` | Diálogos, cajón móvil |
| `shadow-sheen` / `shadow-sheen-accent` | Brillo de laca: 1 px de luz en el borde superior |

---

## 8. Iconografía

- **Librería única:** `lucide-react`. Nada de SVG dibujados a mano para íconos de acción.
- **Trazo:** 1,75 en navegación; por defecto en el resto.
- **Tamaños:** 14 px en controles densos, 16 px en botones y menús, 18 px en navegación y avisos, 20 px en encabezados.
- **Color:** heredan `currentColor`; inactivos en `ink-subtle`, activos en `accent-ink`.
- Todo botón solo-ícono usa `IconButton` (con `aria-label` y tooltip).

Íconos canónicos: Fotos `Images`, Álbumes `SquareLibrary`, Favoritos `Heart`, Drive `FolderClosed`, Documentos `FileText`, Trabajos `Activity`, Ajustes `Settings2`, subir `Upload`/`FolderUp`, descargar `Download`, renombrar `PencilLine`, mover `FolderInput`, eliminar `Trash2`, vista previa `Eye`, reintentar `RotateCw`, buscar `Search`.

---

## 9. Movimiento

Tranquilo y preciso: las cosas "se asientan" en su compartimento.

- **Duraciones:** 120 ms (hover, color), 180 ms (estado), 260 ms (entrada de capas).
- **Curva:** `--ease-out` = `cubic-bezier(0.16, 1, 0.3, 1)`.
- **Animaciones disponibles:** `animate-fade-in` (velos), `animate-pop-in` (menús, diálogos: opacidad + 3 % de escala + 4 px), `animate-slide-up` (barras flotantes, avisos de carga), `animate-drawer-in` (cajón móvil), `animate-bento` (cargador).
- Solo `opacity` y `transform`. Nunca se anima el tamaño de elementos virtualizados.
- `prefers-reduced-motion` desactiva todo movimiento (regla global en `index.css`).

---

## 10. Layout

```
┌ bandeja (tray) ─────────────────────────────────────────────┐
│ ▣ Bento            ┌ compartimento (surface, rounded-xl) ──┐ │
│                    │ 🔍 Buscar fotos, archivos…  Ctrl K  ● │ │ ← barra superior: búsqueda + estado
│ Biblioteca         ├───────────────────────────────────────┤ │
│  ▢ Fotos           │ Título de página          [Acciones]  │ │ ← PageHeader
│  ▢ Álbumes         │ Descripción breve                     │ │
│  ▢ Favoritos       │ [barra de herramientas]               │ │
│ Archivos           │                                       │ │
│  ▢ Drive           │ contenido                             │ │
│  ▢ Documentos      │                                       │ │
│ Sistema            │                                       │ │
│  ▢ Trabajos        │                                       │ │
│  ▢ Ajustes         │                                       │ │
│ [◐ ☀ ☾]            └───────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

- **Barra lateral** sobre la bandeja, sin superficie propia. Grupos: *Biblioteca*, *Archivos*, *Sistema*. Ítem activo = superficie `raised` + sombra `sm` + ícono en `accent-ink`. Al pie, el selector de tema (Automático / Claro / Oscuro).
- **Barra superior** dentro del compartimento: búsqueda global (`Ctrl/⌘ K`) y la píldora de estado de trabajos, siempre visible y enlazada a Trabajos.
- **Móvil (< 768 px):** el compartimento ocupa toda la pantalla; la barra lateral pasa a cajón (botón de menú, `Escape` y clic fuera lo cierran).
- **Página:** `PageHeader` → barra de herramientas → contenido. Anchos máximos: Ajustes y Trabajos `max-w-6xl`; Fotos, Drive y Búsqueda usan todo el ancho.

---

## 11. Primitivos

Todos en `apps/web/src/components`. No conocen dominio (assets, carpetas, trabajos).

| Primitivo | Notas |
| --- | --- |
| `AppShell`, `Sidebar`, `TopSearch`, `StatusIndicator`, `ThemeSwitcher` | Shell descrito en §10. |
| `BrandMark`, `BrandLogo`, `BentoLoader` | Identidad (§3). |
| `PageHeader` | `title`, `description`, `eyebrow`, `actions`, `children` (barra de herramientas). Un `h1` por página. |
| `Button` | Variantes `primary` (una por zona), `secondary`, `ghost`, `danger`, `danger-ghost`; tamaños `sm` 32, `md` 36, `lg` 44; `leadingIcon`, `trailingIcon`, `loading`. |
| `IconButton` | Variantes `ghost`, `secondary`, `overlay` (sobre medios); tooltip incluido. |
| `Input`, `Select`, `Checkbox` (+ `CheckboxBox`) | Etiqueta siempre presente (`hideLabel` la deja solo para lectores). `Input` admite `leadingIcon`, `trailing`, `hint`, `error`. |
| `SegmentedControl` | Radiogroup con flechas; `iconOnly` para vistas compactas. |
| `Tabs` | Subrayado `accent`, flechas para navegar. |
| `Menu` | Portal con posición fija; ítems con `icon`, `tone: "danger"`, `separatorBefore`; flechas/Home/End. |
| `ui/context-menu` | Radix, mismo aspecto que `Menu`. |
| `Dialog` | Portal, `size`, `description`, `icon`, `tone`; `data-autofocus` elige el foco inicial. |
| `Badge`, `StatusDot` | Tonos `neutral`, `accent`, `success`, `warning`, `danger`, `shu`; `dot` y `pulse` para procesos vivos. |
| `Callout` | Aviso en línea (tonos de `Badge` + `info`). El `role` se pasa explícitamente. |
| `Card` | Compartimento dentro de página (`raised` o `muted`). Nunca anidado. |
| `ProgressBar` | Con `label` es un `progressbar` accesible; sin él, decorativo. |
| `EmptyState`, `LoadingState`, `ErrorState` | Vacío con ícono en baldosa y borde discontinuo; carga con `BentoLoader`; error como aviso `danger`. |
| `Thumbnail`, `VirtualGrid`, `VirtualList` | Las listas virtualizadas no traen marco; `fill` ocupa un padre posicionado. |
| `Tooltip`, `Kbd`, `Spinner` | Ayudas pequeñas. |

Utilidades CSS: `focus-ring` (anillo de foco de 2 px en `focus`), `focus-ring-within`, `field` (aspecto de campo).

---

## 12. Patrones por superficie

- **Fotos:** filas justificadas de alto fijo, agrupadas por mes (título `text-xl`) y día (`text-sm` en `ink-muted`). Las fotos no llevan borde ni sombra; el foco/hover las eleva levemente. Los favoritos muestran un corazón shu pequeño; los videos, una insignia con ▶. El visor es siempre oscuro (`media`), con acciones `overlay`, flechas grandes a los lados y atajos ← → Esc.
- **Álbumes:** cuadrícula de portadas 4:3 con título y conteo; crear álbum es un campo + botón primario en la barra de herramientas.
- **Drive:** árbol de carpetas a la izquierda (como un compartimento estrecho), contenido a la derecha. Barra: ruta, buscar en carpeta, vista grilla/lista (íconos), nueva carpeta, subir. Al seleccionar elementos aparece una **barra de acciones flotante** abajo (`shadow-lg`, `animate-slide-up`). La carga se muestra como tarjeta flotante con progreso. Arrastrar archivos activa un velo `accent-soft` con borde discontinuo `accent`.
- **Búsqueda y Documentos:** campo grande con filtros compactos en una fila; resultados agrupados por tipo con miniatura, título, motivo de coincidencia (con ícono `Sparkles` en `accent-ink`) y relevancia como barra.
- **Trabajos:** cifras en una cuadrícula bento (activos destacados), tabla con insignias de estado con punto (`pulse` en ejecución) y reintento explícito.
- **Ajustes:** navegación de categorías a la izquierda; "Resumen" como cuadrícula de tarjetas de salud; barra flotante de cambios sin guardar.
- **Primer inicio:** diálogo `rounded-2xl` con el logo, pasos numerados y opciones como tarjetas seleccionables (`accent-soft` + borde `accent` cuando están activas).

---

## 13. Accesibilidad

- Contraste: texto ≥ 4,5:1 en ambos temas (verificado para cada par `*-ink` / `*-soft`); componentes de interfaz ≥ 3:1.
- Foco visible siempre (`focus-ring`); nunca `outline: none` sin reemplazo.
- Todo control tiene nombre accesible; los solo-ícono, además, tooltip.
- Menús, diálogos, cajón y visor: `Escape` cierra, el foco queda atrapado y vuelve al disparador.
- Grupos de opciones (vista, tema) se recorren con flechas.
- Landmarks: navegación, barra superior con búsqueda, `main`, y la región de estado.

---

## 14. Tema claro y oscuro

- Preferencia del usuario en `localStorage` (`bento:theme`): `system` (por defecto), `light`, `dark`. `lib/theme.ts` escribe `data-theme` en `<html>` y escucha cambios del sistema.
- Los tokens cambian solos mediante `color-scheme` + `light-dark()`. Si hace falta lógica específica existe la variante `dark:`; úsala lo mínimo.
- El visor de medios ignora el tema: siempre `media` (oscuro).

---

## 15. Lista de comprobación

- [ ] Solo tokens de marca; ningún hex ni color de Tailwind por defecto.
- [ ] Una acción primaria por zona; destructivas en `danger` y con confirmación que explique la consecuencia.
- [ ] Como máximo un elemento `shu` visible.
- [ ] Radios anidados correctos; nada de tarjetas dentro de tarjetas.
- [ ] Íconos de `lucide-react`, tamaños de §8.
- [ ] Textos en el diccionario, con tildes y en *sentence case*.
- [ ] Estados vacío, carga y error cubiertos.
- [ ] Funciona en claro, oscuro y a 360 px de ancho.
