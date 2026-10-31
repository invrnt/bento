> Superseded by `architecture/telegram-first.md` from Stage 14 on: Bento uses the user's Telegram account via MTProto, not the Bot API. Kept for history.

# Product: Storage And Telegram

## Scope

Storage abstracts blob persistence. Local mode is required; Telegram mode is optional but part of MVP.

## Local Storage

- `LocalBlobStoreAdapter` stores originals in local volumes.
- Works with no Telegram config.
- Used by default through `STORAGE_BACKEND=local`.

## Telegram Storage

- Use local Telegram Bot API server in `--local` mode.
- Private channels: `raw`, `thumbs`, `journal`.
- Bot must be admin in channels.
- Store Telegram identifiers in SQLite: `chat_id`, `message_id`, `file_id`, `file_unique_id`, `kind`.
- Upload originals as documents.
- Download blobs on demand.
- Retry temporary failures.
- Apply simple rate limiting.
- Do not use Telegram history as business state.

## Environment

- `STORAGE_BACKEND=telegram`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_RAW_CHAT_ID`
- `TELEGRAM_THUMBS_CHAT_ID`
- `TELEGRAM_JOURNAL_CHAT_ID`

## Encryption

Telegram adapter must accept encrypted blobs and must not assume plaintext.

## Ownership

Local storage owner: storage-agent.
Telegram owner: telegram-storage-agent.
