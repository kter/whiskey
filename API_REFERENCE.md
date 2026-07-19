# Whiskey Log API Reference

Base URLs:

- Development: `https://api.dev.whiskeybar.site`
- Production: `https://api.whiskeybar.site`

## Authentication

Private review routes require a Cognito **ID token**.

```http
Authorization: Bearer <id_token>
```

Access tokens are not accepted by the reviews Lambda. API Gateway validates the token first, and the Lambda rechecks `aud` and `token_use=id`. Local invocations without API Gateway perform complete RS256, expiry, issuer, audience, and token-use validation.

## Pagination

Review collection routes accept:

- `limit`: 1–100, default 20
- `next_token`: opaque continuation token returned by the previous response

Collection responses use this shape:

```json
{
  "results": [],
  "reviews": [],
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

### `GET /api/whiskeys/ranking`

Returns the existing whiskey ranking result. Authentication is not required.

## Reviews

`serving_style` uses one of `NEAT`, `ROCKS`, `WATER`, `SODA`, or `COCKTAIL`. Ratings are numeric values from 1 through 5. Dates use the full-date form `YYYY-MM-DD`.

### `POST /api/reviews`

Creates a private review unless `is_public` is explicitly true. The referenced whiskey must already exist.

```json
{
  "whiskey_id": "425757e4-5d6f-4d09-89bc-1f2eb00510e9",
  "rating": 4.5,
  "notes": "Smoky and complex",
  "serving_style": "NEAT",
  "date": "2026-07-19",
  "is_public": false
}
```

Required fields are `whiskey_id`, `rating`, and `date`. `notes` is limited to 2,000 characters. Daily user and global creation limits can produce `429 Too Many Requests`.

### `GET /api/reviews?limit=20&next_token=...`

Returns the authenticated user's reviews. Responses include `Cache-Control: private, no-store`.

### `GET /api/reviews/{id}`

Returns one review only when it belongs to the authenticated user. Missing and foreign reviews both return 404.

### `PUT /api/reviews/{id}`

Updates an owned review. Mutable fields are `rating`, `notes`, `serving_style`, `date`, and `is_public`. `whiskey_id` cannot be changed.

### `DELETE /api/reviews/{id}`

Deletes an owned review. Missing and foreign reviews both return 404.

### `GET /api/reviews/public?limit=20&next_token=...`

Returns public reviews without authentication. Public listing is available only on this dedicated path; `?public=true` on `/api/reviews` is not supported. User identifiers are omitted.

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
