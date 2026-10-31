# UI Primitives

Shared primitives belong in `apps/web/src/components`. Feature-specific variants belong in feature folders. Visual rules for each primitive are in `design-system/brand.md` §11.

Required primitives:

- Shell: `AppShell`, `Sidebar`, `TopSearch`, `StatusIndicator`, `ThemeSwitcher`
- Identity: `BrandMark`, `BrandLogo`, `BentoLoader`
- Layout: `PageHeader`, `Card`
- Actions: `Button`, `IconButton`, `Menu`, `ui/context-menu`
- Forms: `Input`, `Select`, `Checkbox` (`CheckboxBox`), `SegmentedControl`
- Overlays: `Dialog`, `Tooltip`
- Navigation: `Breadcrumb`, `Tabs`
- Feedback: `Badge` (`StatusDot`), `Callout`, `ProgressBar`, `Spinner`, `EmptyState`, `LoadingState`, `ErrorState`
- Media and collections: `Thumbnail`, `VirtualGrid`, `VirtualList`
- Small: `Kbd`

Rules:

- Use `lucide-react` icons for common actions: upload, download, rename, move, delete, favorite, retry, settings, search, grid/list.
- Icon-only controls use `IconButton` (accessible label and tooltip built in).
- One `primary` button per zone; destructive actions use `danger` and a confirmation dialog.
- Do not nest cards inside cards.
- Keep repeated item cards stable in size.
- Shared primitives do not know about assets, folders, albums, jobs, or Telegram.
- Domain behavior is composed in feature modules.
