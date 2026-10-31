# Motion And Interaction

Motion is calm and precise: elements settle into their compartment. Tokens and rationale: `design-system/brand.md` §9.

## Motion

- Use `120ms` (hover/color), `180ms` (state), `260ms` (layer entrance) with `--ease-out`.
- Animate opacity/transform only.
- Respect `prefers-reduced-motion` (global rule in `styles/index.css`).
- Do not animate virtualized item sizes.

## Interactions

- Global search focuses with `Cmd/Ctrl+K`; `Escape` clears it, then blurs it.
- Escape closes menus, dialogs, the mobile navigation drawer and lightbox.
- Menus, segmented controls and tabs support arrow-key navigation.
- Context menus support mouse and keyboard.
- Drag-and-drop upload must show target state and accept fallback file picker.
- Delete is logical delete; confirm destructive actions and explain the consequence.
- Retry job action must be explicit.
- Indexing state is shown inline, not as a blocking modal.
- Selection reveals a floating action bar instead of shifting the layout.

## Feedback

- Upload shows immediate progress in a floating card and then background indexing state.
- Failed partial processing shows warning state but asset remains accessible.
- Search results show match explanation.
- Empty states are concise and actionable.
- The job status pill in the top bar is always visible and links to Jobs.
