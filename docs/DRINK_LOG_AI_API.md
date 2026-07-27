# Drink Log AI / Places API

すべてCognito ID token認証が必要で、レスポンスは`Cache-Control: private, no-store`を返す。

## `POST /api/drink-logs/analyze`

リクエストは`{"s3_key":"tmp/{user}/{uuid}.{ext}"}`。呼出しユーザー所有の一時画像だけを解析し、候補選択に使う短期`analysis_id`を返す。座標は受け取らない。

```json
{
  "analysis_id": "ai-result:{user}:{uuid}",
  "candidates": [
    {
      "brand_text": "カリラ 12年",
      "name_ja": "カリラ 12年",
      "name_en": "Caol Ila 12 Year Old",
      "confidence": 0.9,
      "match_source": "catalog",
      "whiskey_id": "正規化後に完全一致したカタログのID（一致時のみ）"
    }
  ],
  "serving_style": "NEAT",
  "model_id": "jp.anthropic.claude-sonnet-4-6",
  "confidence": 0.9,
  "multiple_detected": false
}
```

`brand_text` は**常にモデルが読み取った銘柄名**で、カタログの名前で置き換えない。
カタログはモデルの読みを上書きせず、一致したときに `whiskey_id` を付けるだけである
（`山崎` を `山崎 12年` に格上げしない）。

| `match_source` | 意味 |
|---|---|
| `catalog` | `normalize_text` による完全一致でカタログの ID を付与した |
| `ai` | カタログに一致が無い。記録は成立し、`whiskey_id` は付かない |

**部分一致・あいまい一致による ID 付与は行わない。** カタログが疎な状態で部分一致を許すと、
`山崎` が `山崎 12年` に、シェリーオークが `ダブルカスク` に確定するといった誤りが起きる。

`multiple_detected` は複数のボトルが検出されたことを示す。この場合フロントは候補を
自動選択せず、ユーザーに選ばせる。`candidates` は最大5件。判別できない場合は空配列になる。

画像はEXIF orientation適用、RGB化、メタデータ除去、JPEG再エンコードを行ってからBedrockへ送る。元画像バイトやEXIFはレスポンスに含めない。入力不正は400、所有権不一致は403、日次上限は429、月次グローバル遮断は503を返す。

## `POST /api/drink-logs/places`

リクエストは`{"lat":35.0,"lng":139.0}`。300m以内のbar/restaurant候補を最大8件、次の配列で返す。

```json
[
  {
    "place_id": "Google Place ID",
    "display_name": "表示名",
    "formatted_address": "住所",
    "attributions": []
  }
]
```

## `POST /api/drink-logs/places/resolve`

リクエストは`{"items":[{"log_id":"...","place_id":"..."}]}`で、最大10件。DrinkLogsの所有者と保存済み`place_id`を確認してからPlace Detailsを取得する。

```json
{
  "results": [
    {
      "log_id": "...",
      "display_name": "表示名",
      "name_source": "google",
      "attributions": []
    }
  ]
}
```

閉店、Place ID失効、項目単位のタイムアウトや不正応答は、その項目だけ`display_name`が`店舗情報を取得できません`のプレースホルダになる。入力不正は400、所有権・place_id不一致は403、費用上限は429、Nearby全体のタイムアウトは504、不正なNearby応答は502を返す。

## Placesデータ保持方針

`drink-log-places-{env}`はGoogle Places API (New)の表示用プロキシとして動作し、Placesコンテンツの永続ストアやリクエスト横断キャッシュにはしない。

- Nearby Searchの`displayName`、`formattedAddress`、`attributions`はその場のレスポンスだけで返し、DynamoDBへ保存しない。
- Place Detailsの`displayName`と`attributions`もその場のレスポンスだけで返し、DrinkLogsやAppStateへ保存しない。
- `lat` / `lng`はPlacesリクエストのためだけに使用し、DrinkLogsへ保存しない。
- 共通Lambda loggerはbody/queryのパラメータ名だけを記録する。`lat`、`lng`、`latitude`、`longitude`、`store`、`brand`の値はredact対象とする。
- APIキーはSecrets Managerから取得してプロセス内だけにキャッシュし、レスポンスやアプリケーションログへ出さない。
- CloudWatch Logsの保持期間は既存インフラ設定に従い、非保持環境は1週間、保持環境は1か月とする。

Googleの帰属表示要件を維持するため、APIから受け取った`attributions`は候補・解決結果の両方で省略せずクライアントへ伝搬する。
