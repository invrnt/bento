# Search Contract

## Request

`GET /api/search?q=&type=&folder_id=&date_from=&date_to=&limit=&cursor=&origin=`

Parameters:

- `q`: search text.
- `type`: optional result/media type filter.
- `folder_id`: optional Drive scope.
- `date_from`, `date_to`: optional date filters.
- `limit`: default `50`.
- `cursor`: pagination cursor.
- `origin`: optional; how this device obtained the asset: `device` (picked here), `peer` (synced from another device; which one is not recorded), `telegram` (either Telegram origin), `telegram_inbox`, `telegram_import`. Folders and albums are left out while it is set.

## Response

```json
{
  "items": [
    {
      "id": "hit-id",
      "type": "photo",
      "asset_id": "asset-id",
      "title": "IMG_001.jpg",
      "subtitle": "Mar 2026",
      "thumbnail_url": "/api/assets/asset-id/thumbnail",
      "score": 0.91,
      "reason": "Coincidio por OCR y tipo de documento",
      "processing_state": "indexed",
      "match_reasons": ["ocr_text", "document_type"],
      "snippet": {"text": "…Total a pagar: 99 € por el café…", "highlights": [[28, 32]], "source": "ocr_text"},
      "folder_id": "folder-id",
      "folder_name": "Impuestos",
      "mime_type": "image/jpeg",
      "origin": "device"
    }
  ],
  "facets": [
    { "type": "photo", "count": 12 }
  ],
  "next_cursor": null
}
```

- `reason` stays the Spanish sentence for the web UI; clients that localize use `match_reasons`, strongest first: `ocr_text`, `filename`, `folder_name` (the file's folder, or the folder hit itself), `album` (an album holding the photo, or the album hit itself), `semantic`, `metadata`, `document_type`, `exif_date` (capture date), `date` (added date, no capture date known), `indexed_text`, `recent`.
- `snippet`: excerpt of the matched text (OCR text, file name, folder name, or album title, in that preference) with `highlights` as `[start, end)` offsets in UTF-16 code units; `null` when nothing textual matched.
- `folder_id`/`folder_name`: the containing folder (for folder hits, the parent). `origin` is `null` for folders and albums.

## Requirements

- Include explanation for every result.
- Include processing/indexing state.
- Degrade without OCR or embeddings.
- Search folders and albums as first-class results.
- Apply Drive/Photos scoped filters when requested.
