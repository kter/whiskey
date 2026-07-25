# Task 13: HEIC アップロード対応 + 複数枚（一括）登録

## 背景・スコープ
実機（iOS）受入試験で2つの要望が出た。**フロントエンドのみ**で対応する。

1. **HEIC/HEIF アップロード対応** — iOS の既定形式。現状は明示拒否している。
2. **複数枚の一括登録** — N 枚選ぶと、各写真がそれぞれ別の飲酒ログとして登録される
   （1枚 = 1杯。まとめて登録）。**確定した仕様: N枚 → N件のログ**（1件に複数写真ではない）。

**変更してよいのは `frontend/` のみ。** `lambda/`・`infra/`・DynamoDB スキーマ・API 契約は
**一切変更禁止**（`upload-url` / `analyze` / `create` は既に写真1枚単位で、バッチはその繰り返し）。
`git diff` が frontend 以外に触れていたら不合格。

---

## Feature 1: HEIC 対応（`frontend/utils/imageResize.ts`）

現状: `resizeImage()` は HEIC を検出すると `HeicUnsupportedError` を投げる。フロントは常に
canvas で JPEG に再エンコードするため、**HEIC を JPEG blob に変換してから既存のリサイズ経路に
流せばバックエンドは無改修**（アップロードの content_type は `image/jpeg` のまま）。

### 実装
- `resizeImage(file)` から HEIC 拒否を撤廃し、次の挙動にする:
  1. HEIC 判定（MIME `image/heic`/`image/heif` または拡張子 `.heic`/`.heif`）。
  2. **ネイティブデコード優先**: まず既存の `loadImage(file)`（`<img>` + objectURL）を試す。
     iOS は全ブラウザ WebKit で HEIC をネイティブデコードできるため、これで成功する。
  3. ネイティブが失敗（Chrome/Android は HEIC 不可で `loadImage` が reject）**かつ HEIC の場合のみ**、
     `heic2any` を **動的 import**（`const { default: heic2any } = await import('heic2any')`）して
     `heic2any({ blob: file, toType: 'image/jpeg', quality: 0.92 })` で JPEG Blob に変換し、
     その Blob を `loadImage` → canvas リサイズ経路へ渡す。
     - `heic2any` は `Blob | Blob[]` を返す。配列なら先頭を使う。
  4. 非 HEIC は従来通り。
- 出力は常に JPEG ≤ 3.5MB（既存の `resizeAttempts` パイプラインを流用）。
- 変換失敗時は明確な日本語エラー（例: `HEIC画像を変換できませんでした。JPEGで撮り直してください。`）。
- `HeicUnsupportedError` クラスは削除するか、未使用になるなら export を含め除去（lint を通すこと）。
- **依存追加**: `frontend/package.json` に `heic2any` を**正確なバージョンでピン止め**（`^` を付けない）。
  最新安定版を使う。`package-lock.json` も更新（`npm install heic2any@<ver> --save-exact`）。
- **動的 import 必須**（`import()`）— メインバンドルに libheif WASM(~1.5MB) を載せず、HEIC 変換が
  必要なときだけ code-split で読み込む。iOS はネイティブ成功するので通常 WASM を落とさない。
- CSP: 現状コンテンツ CSP は未実装のため変更不要。もし将来 CSP を導入する場合は
  `script-src` に `'wasm-unsafe-eval'` が必要、とコードコメントに一言残す。

---

## Feature 2: 複数枚の一括登録（`frontend/pages/logs/new.vue` + 新規 `composables/useDrinkLogBatch.ts`）

### 入力
- ファイル input を `multiple` にし、`accept` に HEIC を追加:
  `accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" multiple capture="environment"`。
- 1 枚でも N 枚でも同じ経路で扱う（**N=1 の単写真フローも壊さないこと**）。
- **1 回の登録は最大 10 枚**。超過選択時は先頭10枚に制限し「一度に登録できるのは10枚までです」と案内。

### 写真ごとの前処理パイプライン（既存 `useDrinkLogs` の primitive を再利用）
各写真について: `resizeImage`（Feature 1 込み）→ `getUploadUrl(contentType)` → `uploadToS3(...)` →
`analyze(s3_key)`。**同時実行は最大 2**（全並列は API GW スロットリングで 429 を誘発するため）。
写真ごとに状態表示（`処理中` / `解析完了` / `失敗`）と個別のエラーメッセージ。

### 確認 UI（解析後）
写真ごとに**確認カードの一覧**を表示（成功したものだけカード化、失敗はエラー行 + 再試行）。
- カード: サムネイル（リサイズ済み blob の objectURL）
  - AI 銘柄候補ドロップダウン（`候補を使わず手入力` + candidates）+ 銘柄手入力欄
    （既存単写真と同じロジック: `candidateIndexAfterBrandEdit` で編集時に候補選択を解除）
  - 飲み方ピル（NEAT/ROCKS/WATER/SODA/COCKTAIL）
  - 任意: 評価（★）・ノート（各カード個別）
  - **候補が空（解析 degrade）でも手入力の銘柄で保存可能**にする（`create` は candidate_index なしの
    `brand_text` 手入力を受理する。task 07b で対応済み）。
- **共有フィールド（全カードに適用、フォーム上部）**: 店名（自由入力）+ 「近くの店を探す」
  （位置情報 → Places 検索）。バッチは同一店の想定なので店名・place_id は共有。日時は各ログ
  サーバー時刻（現在）。Google 帰属表示は既存コンポーネントを流用。

### 保存（一括）
- 各カードについて payload を構築（`analysis_id` + `candidate_index` または手入力 `brand_text` +
  共有 store（name/place_id）+ カード個別の serving/rating/notes）→ `createLog`。
  **同時実行は最大 2**。カードごとに保存状態（保存中/完了/失敗）を表示。
- **部分失敗の分離**: 解析失敗・保存失敗・429/503（`本日の上限に達しました`）が出ても他は進める。
  失敗した項目だけ残して再試行できる導線を用意。成功した保存は失われない。
- 全件保存完了で、保存済みログを共有タイムラインストアへ `upsertLogs` し `/logs` へ遷移。
  一部失敗が残る場合は成功分を反映しつつエラー要約を表示（自動遷移しない）。

### 後方互換
- N=1 のときも新カード UI で 1 枚だけ表示されれば良い（既存の単写真挙動＝候補プリフィル・手入力・
  飲み方・店名・評価・ノートが保てること）。既存の単写真 E2E 相当が壊れないこと。

---

## テスト（vitest、`frontend/tests/`）
- `imageResize`: HEIC 分岐 — `heic2any` の動的 import と `loadImage` のネイティブ失敗をモックし、
  変換経路が JPEG blob を返すことを検証。非 HEIC は従来通り。既存テストを緑に保つ。
- バッチ orchestration（`useDrinkLogBatch` を新設した場合はその単体テスト）:
  `useDrinkLogs` primitive をモックし、N 入力で N 回 `createLog` が呼ばれること、
  部分失敗が分離されること、**同時実行が 2 を超えないこと**を検証。
- 既存の `logs/new` 関連テストがあれば更新。

## 受入条件
- `cd frontend && npm ci && npm run lint && npm run typecheck && npm run test -- --run && npm run generate` が全て成功。
- HEIC ファイルが選択でき、JPEG としてアップロードされる（テストで検証、実機確認はユーザー）。
- N 枚選択で N 件のログが作られる。部分失敗が分離される。単写真も従来通り動く。
- `git diff` は `frontend/` のみ（`lambda/`・`infra/`・スキーマ・API 契約は無変更）。
- 既存コードのスタイル踏襲（composables、stone/amber Tailwind、日本語 UI 文言）。

## 実装メモ
- HEIC は必ず**動的 import**で code-split（メインバンドルを太らせない）。バージョンは exact ピン。
- 位置情報・Places・帰属表示は既存の `useGeolocation` / `useVisiblePlaceResolver` /
  `GoogleAttributions` / `DrinkLogStoreDisplay` を流用。
- バッチの同時実行制御は小さなセマフォ（Promise プール、上限2）で実装。
