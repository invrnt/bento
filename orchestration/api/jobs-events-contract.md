# Jobs And Events Contract

## Job API

`GET /api/jobs` returns:

```json
{
  "items": [
    {
      "id": "job-id",
      "type": "ocr",
      "status": "failed",
      "priority": 3,
      "attempts": 2,
      "max_attempts": 3,
      "asset_id": "asset-id",
      "error": "safe error summary",
      "created_at": "2026-01-01T00:00:00Z",
      "updated_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

`POST /api/jobs/{job_id}/retry` requeues retryable failed jobs.

`POST /api/admin/reindex` enqueues indexing work for existing assets.

## Manifest Events

Event record:

```json
{
  "id": "event-id",
  "type": "asset_created",
  "entity_type": "asset",
  "entity_id": "asset-id",
  "payload": {},
  "created_at": "2026-01-01T00:00:00Z"
}
```

## Event Sinks

- SQLite `manifest_events`.
- Local JSONL export in `data/journal`.
- Telegram journal channel only when `STORAGE_BACKEND=telegram`.

## Required Behavior

- Event write is part of successful use-case completion where practical.
- JSONL export can be async but must be idempotent.
- Telegram journal failure must not corrupt local state; record partial failure and retry.

## Change Stream

`GET /api/events` (Server-Sent Events) announces which topics changed (`library`, `jobs`, `imports`, `sync`) so clients refetch instead of polling; see `api/android-endpoints.md` § 11 Events. It carries no data and replays nothing.
