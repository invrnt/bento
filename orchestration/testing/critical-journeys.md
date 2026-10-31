# Critical Journeys

These journeys must be covered before release.

1. Fresh clone setup: copy `.env.example`, run Docker Compose, open app.
2. Local mode upload: upload file, see it in Drive, download it.
3. Photo upload: upload image, thumbnail appears, timeline groups by date, lightbox opens.
4. Folder operations: create, rename, move, list, logical delete.
5. Jobs visibility: thumbnail/OCR/embedding jobs appear, complete or fail visibly, retry works.
6. Search by filename: result appears without OCR/embeddings.
7. Search by OCR: image/PDF text appears after indexing.
8. Semantic search: indexed photo appears when embedding provider is enabled or mocked.
9. Disabled embeddings: app still searches by filename/OCR/metadata.
10. Disabled Telegram/local mode: app works with `STORAGE_BACKEND=local`.
11. Telegram mode smoke: with `STORAGE_BACKEND=fake` (and manually with a real account), sign in by QR, create the vault, upload, see the encrypted parts in the Files channel, download, and stream a video range.
12. Manifest export: important events are persisted and JSONL export contains them.
13. Desktop fresh install: install and open on Windows, macOS, and Linux without Docker/Python/Node; local mode reaches a ready window.
14. First-run setup: choose a valid data directory, keep local storage, skip AI, finish, relaunch, and retain choices.
15. Editable settings: change worker/OCR configuration, see validation and restart scope, save, restart only affected sidecars, and observe the new effective revision.
16. Secret safety: after Telegram sign-in and vault creation, relaunch successfully and verify the session, keyring, device key, and wrapping key are absent from SQLite, renderer storage, API responses, exports, and logs; only `data/secure/*.bin` ciphertext exists.
17. Invalid settings rollback: apply an unavailable model/path or broken sidecar setting, fail readiness, restore last-known-good configuration, and keep Settings usable.
18. Legacy migration: preview/import a `.env`, report unknown/locked keys, redact secrets, and stop depending on the file after a successful desktop import.
19. Headless compatibility: Docker environment overrides remain effective, appear locked with source explanation, and existing local-mode journeys remain green.

## Telegram-First Journeys (Stage 17)

20. First run end to end: welcome → QR sign-in → vault created → backup folders chosen → recovery kit saved (PDF on desktop) → library ready; the Telegram account shows the `Bento` chat folder with three muted channels.
21. Second device by code: device A shows a code; device B (not signed in to Telegram) enters it; emojis match; A approves; B is signed in to Telegram and unlocked without the phone; B bootstraps and shows A's library.
22. Second device fallback: relay unavailable; B signs in with its own QR, requests access; A reviews emojis and approves via the Sync channel.
23. Convergence: concurrent rename/move/favorite/album edits and delete/restore on A and B converge identically; purge removes the item everywhere and deletes its Telegram parts.
24. Recovery: a fresh device with only the Telegram account and the recovery code restores the whole library.
25. Device removal: removing B from A closes B's Telegram session (or explains the 24 h restriction), rotates keys, forces a new recovery kit, and B can no longer read new batches.
26. Automatic backup: a new photo in a backed-up folder appears in Photos and on the other device without user action; pause and pause-on-battery stop folder uploads; source deletions never delete from Bento.
27. Inbox: a file forwarded to `Bento · Bandeja` appears in Bento, the message gets ✅, and is removed after the keep window.
28. Share and import: sending a file to a Telegram chat delivers the original; importing media from Saved Messages adds them without duplicates.
29. Offline and flood wait: uploads queue offline and resume; a simulated flood wait shows a calm status and resumes automatically.
30. Tray and deep link: closing the window keeps Bento in the tray with live status; opening `bento://join?v=1&c=…` jumps to the join screen.
