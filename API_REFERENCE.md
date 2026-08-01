# Whiskey Log API Reference

Base URLs:

- Development: `https://api.dev.whiskeybar.site`
- Production: `https://api.whiskeybar.site`

## Authentication

Private drink-log routes require a Cognito **ID token**.

```http
Authorization: Bearer <id_token>
```

Access tokens are not accepted. API Gateway validates the token first, and each authenticated Lambda rechecks `aud` and `token_use=id`. Local invocations without API Gateway perform complete RS256, expiry, issuer, audience, and token-use validation.

## Pagination

Drink-log collection routes accept:

- `limit`: 1–100, default 20
- `next_token`: opaque continuation token returned by the previous response

Collection responses use this shape:

```json
{
  "results": [],
  "count": 0,
  "next_token": null
}
```

## Whiskeys

### `GET /api/whiskeys`

Returns the whiskey list. Authentication is not required.

### `GET /api/whiskeys/search?q={query}`

Searches whiskey names in English or Japanese. Authentication is not required. Japanese query values must be URL encoded.

### `GET /api/whiskeys/suggest?q={query}`

Returns whiskey-name suggestions. Authentication is not required.

### `GET /api/whiskeys/search/suggest?q={query}`

Compatibility alias for suggestions. Authentication is not required.

## Drink logs

Drink-log datetimes use normalized RFC3339 UTC strings. A stored item has this shape:

```json
{
  "id": "log-id",
  "user_id": "cognito-sub",
  "status": "complete",
  "datetime": "2026-07-21T12:34:56Z",
  "s3_image_key": "logs/cognito-sub/log-id.jpg",
  "tmp_s3_key": "tmp/cognito-sub/upload-id",
  "quota_allocated": true,
  "whiskey_id": "optional-whiskey-id",
  "brand_text": "Ardbeg 10",
  "brand_source": "matched",
  "serving_style": "NEAT",
  "store": {"name": "Bar name", "place_id": "optional-place-id"},
  "notes": "optional notes",
  "rating": 4.5,
  "ai": {"model_id": "jp.amazon.nova-2-lite-v1:0", "confidence": 0.93},
  "created_at": "2026-07-21T12:35:00Z",
  "updated_at": "2026-07-21T12:35:00Z"
}
```

`status` is `pending`, `complete`, or `deleting`; `brand_source` is `ai`, `manual`, or `matched`. `tmp_s3_key`, `whiskey_id`, `notes`, `rating`, `ai`, and `store.place_id` are optional. `store.name` is user input and may be empty. GPS coordinates and Google-provided display names are never persisted.

### `POST /api/drink-logs/upload-url`

Creates a constrained temporary-image upload URL. The temporary object is under `tmp/` and expires after two days.

### `POST /api/drink-logs/analyze`

Analyzes a temporary image using an allowlisted Bedrock inference profile.

### `POST /api/drink-logs/places`

Looks up nearby Places candidates. Coordinates are accepted in the JSON body, not the URL, and are not stored.

### `POST /api/drink-logs/places/resolve`

Resolves an owned log's optional Place ID for display without persisting a Google display name.

### `POST /api/drink-logs`

Creates a drink log and moves the sanitized image from `tmp/` to `logs/`.

The request may include `datetime` as an RFC 3339 timestamp with an explicit
UTC offset or `Z` (for example, `2026-08-01T21:30:00+09:00`). It must not be
earlier than `2000-01-01T00:00:00Z` or later than five minutes after the server's
current time. The server normalizes an accepted value to UTC; when omitted, the
server's processing time is used. `datetime` is create-only and is not accepted
by `PUT /api/drink-logs/{id}`.

### `GET /api/drink-logs?limit=20&next_token=...&brand=...&store=...&place_id=...`

Returns the authenticated user's timeline. `brand`, `store`, and `place_id` are optional filters.

### `GET /api/drink-logs/{id}`

Returns one owned drink log.

### `PUT /api/drink-logs/{id}`

Updates an owned drink log.

### `DELETE /api/drink-logs/{id}`

Marks and removes an owned drink log through the recoverable deletion flow.

## Errors

Validation failures return field-specific errors:

```json
{
  "error": "Validation failed",
  "fields": {
    "rating": "Must be a number from 1 to 5"
  }
}
```

Unexpected failures return a generic message and a request ID. Internal exception details are logged but never included in the response.

```json
{
  "error": "Internal server error",
  "request_id": "request-id"
}
