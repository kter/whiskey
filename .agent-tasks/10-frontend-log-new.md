# Task 10: 記録ページ（フォトファースト飲酒ログ）+ 利用規約/プライバシー

新規: `frontend/pages/logs/new.vue`, `frontend/composables/useDrinkLogs.ts`, `frontend/composables/useGeolocation.ts`, `frontend/utils/imageResize.ts`, `frontend/pages/terms.vue`, `frontend/pages/privacy.vue`。変更: `frontend/layouts/default.vue`（ナビ「記録」+ フッターに規約/プライバシー）。テスト: `frontend/tests/` に vitest。**バックエンド・インフラは変更しない**（06〜09確定）。

パターン: `composables/useApi.ts`（`request<T>(path, {auth:'none'|'optional'|'required', query, body, method})`）、`useAuth`（`currentUserId`/`getToken`/`waitForAuthReady`/`isAuthenticated`）、フォーム雛形は `pages/reviews/new.vue`（Tailwind stone/amber、serving はラジオピル、star rating）。既存 vitest は `frontend/tests/composables`・`frontend/tests/pages`。

## API 契約（実装済みバックエンド・厳守）

- `POST /api/drink-logs/upload-url` body `{content_type:"image/jpeg"|"image/png"|"image/webp"}` → `{upload_url, fields, s3_key}`（presigned POST。`fields` を multipart で送る）。
- `POST /api/drink-logs/analyze` body `{s3_key}` → `{analysis_id, candidates:[{brand_text,name_ja,name_en,confidence}], serving_style, model_id, confidence}`（候補は空配列もあり得る）。
- `POST /api/drink-logs` body `{analysis_id, candidate_index?, brand_text?, serving_style?, store?:{name,place_id?}, notes?, rating?}` → `{id, status:"complete", image_url, brand_text, brand_source, serving_style, store, datetime, …}`。
  - **候補選択時**: `candidate_index` を送る（brand_source=ai/matched）。
  - **手入力/候補ゼロ/候補を編集**: `candidate_index` を送らず `brand_text` を送る（brand_source=manual）。**両方送ると brand_text 上書きで manual 扱い**。
  - store/serving_style/rating/notes はユーザー入力として送れる。**datetime はサーバーが保存時刻に固定**（この iteration では編集不可 — フォームには「記録日時: 今」と表示）。
- `POST /api/drink-logs/places` body `{lat,lng}` → `[{place_id, display_name, formatted_address, attributions}]`（**GET でなく POST**）。
- `GET /api/drink-logs` → `{results:[…], count, next_token}`。
- 認証: 全て `auth:'required'`（drink-logs は Cognito 認可必須）。`useApi` が idToken を Bearer 付与。

## `utils/imageResize.ts`

`resizeImage(file: File): Promise<{ blob: Blob; contentType: string }>`:
- **HEIC 拒否**: MIME が `image/heic`/`image/heif` または拡張子 `.heic`/`.heif` は `HeicUnsupportedError` を投げる（Chrome は HEIC を canvas デコードできない）。
- canvas で長辺最大 **1600px** に縮小、`image/jpeg` q0.85 で `toBlob`。
- **`blob.size > 3.5MB`（3670016）なら品質(0.85→0.7→0.55)・寸法(1600→1280→1024)を段階的に下げて再試行**、それでも収まらなければ `ImageTooLargeError`（固定パラメータは上限保証にならない）。
- 出力 contentType は常に `image/jpeg`（png/webp 入力も JPEG 化 — バックエンドの content_type は upload-url に渡す値と一致させる。**入力が png/webp のままアップロードしたい場合は縮小せず元 MIME で送る選択肢**もあるが、簡潔さのため JPEG 統一でよい。ただし upload-url の content_type と実バイトを一致させること）。
- 単体テスト: HEIC 拒否・大サイズの段階縮小・長辺制限。

## `composables/useDrinkLogs.ts`

`useApi` 経由で: `getUploadUrl(contentType)`, `uploadToS3(uploadUrl, fields, blob)`（**presigned POST は multipart/form-data。進捗が要るので XHR + `upload.onprogress`** — 標準 fetch にアップロード進捗イベントが無い。進捗コールバック引数を受ける）, `analyze(s3_key)`, `createLog(payload)`, `listLogs({limit,next_token,brand,store,place_id})`, `getLog(id)`, `updateLog(id, payload)`, `deleteLog(id)`, `searchPlaces(lat,lng)`, `resolvePlaces(items)`。**状態は `useState` ベースの共有ストア**（タスク11のタイムラインと共有 — 保存直後の upsert 用。ID重複排除/日時ソートはタスク11で契約化）。エラーは `ApiError`（useApi）を握って UI 表示用に正規化。

## `composables/useGeolocation.ts`

- `requestPosition(): Promise<{lat,lng} | null>` — `navigator.geolocation.getCurrentPosition` をラップ。**明示的ユーザー操作（「近くの店を探す」ボタン）後のみ呼ぶ**。
- **初回同意説明**: 「座標はサーバー経由で Google Places に送られ店候補検索にのみ使用・保存しない・手入力でも登録可能」を表示してから取得（座標非保存 + 第三者送信の事前開示）。拒否/失敗/タイムアウトは `null` を返しフォームは手入力にフォールバック。

## `pages/logs/new.vue`（モバイルファースト）

1. `<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment">`。選択 → `resizeImage`（HEIC は日本語案内「JPEGで撮影/選択してください」）→ プレビュー表示。
2. `getUploadUrl` → `uploadToS3`（進捗バー、XHR onprogress）→ 並列で `analyze` +（「近くの店を探す」押下時のみ `requestPosition`→`searchPlaces`）。
3. **確認フォーム**: 銘柄候補ドロップダウン（`candidates`、選択で candidate_index）+ **自由入力欄**（編集したら candidate_index を捨て brand_text 送信=manual）、飲み方ピル（`serving_style` 単一選択、AI 検出値をプリフィル）、店候補リスト+自由入力+**Google帰属表示（`attributions`、ロゴ/帰属要件準拠）**、任意 rating（★）・notes、「記録日時: 今」表示（編集不可）。
4. **保存** → `createLog(payload)` → タイムライン（`/logs`）へ遷移。保存レスポンスを共有ストアへ upsert（タスク11連携）。
5. **グレースフルフォールバック**: 解析中スピナー/スケルトン、AI項目は全編集可、位置情報拒否/解析空振り（候補ゼロ→手入力必須の案内）/429（レート上限）/503（サービス一時停止）を日本語で表示し破綻しない。

## `pages/terms.vue` / `pages/privacy.vue`（公開ページ・`auth:'none'`）

Places ポリシー要件。フッターからリンク。内容（日本語）:
- **利用規約**: Google Maps/Places 利用規約への言及、サービスの位置づけ。
- **プライバシーポリシー**: ① **GPS の Google Places 送信**（目的=店候補検索・**非保存**・手入力代替可）② **Bedrock 画像解析**（銘柄/飲み方判別・**APAC 域内クロスリージョン配送**・モデル呼び出しログは無効方針）③ **tmp/ の一時生画像保持**（「2日後に失効処理、物理削除は非同期」と正確に表現 — 「最大2日で削除」とは書かない）④ 保存する店情報は place_id とユーザー入力名のみ（Google 表示名は非永続）⑤ 画像は logs/ にプライベート保存・presigned URL 配信。**Google 表示名を表示する箇所には帰属表示**。

## レイアウト（`layouts/default.vue`）

- 認証済みナビに「記録」（`/logs/new` または `/logs`）リンク追加（既存 stone/amber スタイル）。
- フッター（無ければ新設）に「利用規約」「プライバシーポリシー」リンク。

## 検証

`cd frontend && npm run lint && npm run typecheck && npx vitest run`（全緑）。`npm run generate`（本番ビルド成功）。**vitest**: imageResize（HEIC拒否/段階縮小）、useDrinkLogs（各エンドポイントの path/method/body/auth、XHR 進捗のモック）、useGeolocation（同意フロー・拒否時 null）、logs/new（候補選択→candidate_index / 手入力→brand_text / 候補編集→manual / 位置情報拒否フォールバック / 429・503 表示）。

## してはならないこと

- バックエンド/インフラ/ローカルアダプタの変更。`datetime` をクライアント送信する実装（バックエンド非対応）。GPS 座標や Google 表示名をローカルストレージ/状態に永続化。実 API キーのハードコード。タイムライン一覧ページ本体（`pages/logs/index.vue`・`[id].vue`）はタスク11 — ここでは作らない（ナビリンク先が未実装でも可、または最小プレースホルダ）。コミット作成。
