# Design Tokens

Brand rationale, palette values and usage rules live in `design-system/brand.md`. This file is the implementation contract.

Tokens are CSS custom properties declared in `apps/web/src/styles/tokens.css` inside Tailwind v4 `@theme`, so each token is also a utility (`bg-surface`, `text-ink-muted`, `border-line`, `rounded-lg`, `shadow-md`…).

## Rules

- Tailwind's default color palette is disabled (`--color-*: initial`). Components may only use brand tokens; never hex values, `slate-*`, `teal-*`, etc.
- Every color is OKLCH wrapped in `light-dark(light, dark)`. Theme switching only changes `color-scheme` on `<html>` (see `apps/web/src/lib/theme.ts`).
- New tokens are added to `tokens.css` and documented in `brand.md` in the same change.

## Color

- Structure: `tray` (app background), `surface` (main compartment), `raised` (cards, menus, dialogs, fields), `subtle`, `sunken`, `hover`, `pressed`, `line`, `line-strong`, `scrim`.
- Text: `ink`, `ink-muted`, `ink-subtle`, `ink-inverse`, `tooltip`.
- Interaction (Ai indigo): `accent`, `accent-hover`, `accent-soft`, `accent-soft-hover`, `accent-ink`, `on-accent`, `focus`.
- Brand spark (Shu vermillion): `shu`, `shu-soft`, `shu-ink`. At most one shu element per screen.
- Semantic: `success`, `warning`, `danger` each with `-soft` and `-ink`; `danger-hover`, `on-danger`.
- File kinds: `kind-{folder,pdf,doc,sheet,slides,image,video,audio,archive,text}` and `-soft`.
- Media viewer (theme-independent): `media`, `media-raised`, plus `white`/`black` for overlays.

## Type

- UI font: Geist Variable; data font: Geist Mono Variable. Both bundled via `@fontsource-variable/*` (desktop CSP allows only `font-src 'self'`).
- Base size `14px` (`text-base`); scale `text-2xs` 11 → `text-3xl` 32. Page headings `text-2xl` (24px).
- Letter spacing `0` for body; `tracking-tight` / `tracking-tighter` for headings only.
- Do not scale font size with viewport width.

## Spacing

- Base unit `4px` (Tailwind `--spacing`). Common gaps `8`, `12`, `16`, `24`, `32`.
- Control heights: `32px` dense, `36px` standard, `44px` prominent (`--size-control-*`).

## Radius

Nested rule: outer radius = inner radius + gap.

- `xs` 6px, `sm` 8px (dense controls, menu items), `md` 10px (buttons, fields), `lg` 14px (cards, menus), `xl` 18px (main compartment, dialogs), `2xl` 24px (first-run hero), `full` (badges, pills).

## Elevation

- Hairline borders first. Ink-tinted shadows `xs`, `sm`, `md`, `lg`, `xl`; `sheen` / `sheen-accent` add a 1px lacquer highlight.
- Menus and floating bars use `lg`; dialogs and the mobile drawer use `xl`.

## Motion

- `--ease-out` `cubic-bezier(0.16, 1, 0.3, 1)`; durations `120ms` / `180ms` / `260ms`.
- Animations: `fade-in`, `pop-in`, `slide-up`, `drawer-in`, `bento` (loader).

## Media Sizes

- `thumb_sm`: `256px` max side.
- `thumb_md`: `512px` max side.
- `preview`: `1600px` max side.
- Grid cells must define stable aspect ratio and dimensions.
