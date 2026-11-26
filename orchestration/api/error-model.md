# API Error Model

Use consistent JSON errors:

```json
{
  "error": {
    "code": "asset_not_found",
    "message": "Asset not found",
    "details": {},
    "request_id": "..."
  }
}
```

## Rules

- `code` is stable and machine-readable.
- `message` is developer-readable; frontend maps known codes to localized text.
- `details` contains safe structured context only.
- Never include secrets, full local paths, Telegram tokens, or stack traces in public errors.
- Include `request_id` for logs.

## HTTP Status Mapping

- `400`: validation or unsupported operation.
- `401/403`: reserved for future local auth.
- `404`: missing asset, folder, album, job.
- `409`: duplicate conflict, invalid move cycle, state conflict.
- `413`: upload too large.
- `415`: unsupported media type for preview/OCR path.
- `422`: request schema validation.
- `429`: Telegram/rate limit.
- `500`: unexpected internal failure.
- `503`: dependency unavailable, such as Telegram in telegram mode.

## Required Codes

- `asset_not_found`
- `folder_not_found`
- `album_not_found`
- `job_not_found`
- `duplicate_asset`
- `invalid_folder_move`
- `unsupported_media_type`
- `upload_too_large`
- `storage_unavailable`
- `telegram_not_configured`
- `ocr_disabled`
- `embeddings_disabled`
- `job_not_retryable`
- `validation_failed`
- `settings_revision_conflict`
- `settings_probe_failed`
- `settings_restart_failed`
- `settings_source_locked`
- `secret_store_unavailable`
- `smart_search_state_conflict` (`409`, `details: {state, event}`): the smart search action is not allowed in the current state (maps the domain's `illegal_smart_search_transition`).
- `smart_search_no_space` (`409`, `details: {required_bytes, free_bytes}`): less free disk than the model size plus 10 %.
- `invalid_model_spec` (`400`): unknown smart search model id, unsupported dimensions, or a malformed model manifest.
