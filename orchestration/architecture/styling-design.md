# Styling And Design Architecture

Use Tailwind v4 with brand tokens declared in `@theme` (`apps/web/src/styles/tokens.css`). The brand, palette and visual language are defined in `design-system/brand.md`. Shared UI primitives live in `apps/web/src/components`; feature-specific compositions live in `apps/web/src/features`.

## Layout

- Tray + compartments: the sidebar sits on the `tray` background; content lives in one raised, rounded main compartment.
- Persistent sidebar grouped as Biblioteca / Archivos / Sistema, with the theme switcher at its foot; it becomes a drawer below `768px`.
- Persistent top bar inside the compartment with global search and the job status pill (always visible, links to Jobs).
- Main content region with route-specific content, each page starting with `PageHeader`.
- Settings reachable from sidebar.
- Light, dark and system themes.

## Product Feel

This is a private local productivity app, not a marketing site. Use calm, scan-friendly layouts with generous negative space (*ma*). Avoid decorative hero sections and one-note color themes: neutrals carry the UI, Ai indigo marks interaction and a single Shu vermillion accent is the brand spark.

## UI Requirements

- Drive: breadcrumb, grid/list toggle, folder cards, file cards, drag/drop upload, context menu, rename, move, delete, download, preview.
- Photos: virtualized timeline, date grouping, grid, lightbox, video basic viewer, favorite toggle, album assignment.
- Search: grouped results, filters, match explanation, thumbnails, indexing state.
- Jobs: status, retry action, visible failures.

## Component Rules

- Shared primitives are generic and domain-neutral.
- Feature modules own domain-specific components.
- Use icon buttons with tooltips for common actions.
- Radii follow the nested rule in `design-system/tokens.md` (cards `14px`, main compartment and dialogs `18px`).
- Stable dimensions are required for grids, thumbnails, icon buttons, and toolbars to avoid layout shift.
- Text must not overflow buttons, cards, or sidebars at supported desktop/mobile widths.
