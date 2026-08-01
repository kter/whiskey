# Task 19: ログ詳細画面の表示変更（Issue #26）

## 背景

Issue #26 の4項目:

1. 記録情報のトグルメニューがあるがこれを削除する
2. 状態項目を削除する
3. Google Maps の文言をリンカブルにして、クリックするとそのバーの情報が Google Map で見られるようにする。**緯度経度で指定するのではなく、店名で指定すること**
4. 日時に表示する日付は作成日ではなく、**撮影日**にすること

1〜3 はフロントのみ。**4 はバックエンドの変更を伴う** — 現状 `datetime` は Lambda が
保存時刻で埋めており（`lambda/drink-logs/index.py:580` 付近 `"datetime": now`）、
クライアントから送る経路が存在しない（`CREATE_FIELDS` に `datetime` が無い）。

## スコープ

`frontend/` `lambda/` `tests/` とドキュメント。**`infra/` は変更しない**
（テーブル定義・GSI・IAM・環境変数はいずれも変更不要）。

---

## 変更1: 記録情報トグルの削除（フロント）

`frontend/pages/logs/[id].vue` の `<details>…<summary>記録情報</summary>…</details>`
ブロックを丸ごと削除する。記録ID・ユーザーID・作成日時・更新日時・AI解析JSON の表示も
一緒に消える。`log.created_at` / `log.updated_at` / `log.ai` を参照する箇所が他に無いか
grep で確認し、型定義（`DrinkLog`）自体は**変更しない**（API は引き続き返すため）。

## 変更2: 「状態」項目の削除（フロント）

同ファイルの `<dt>状態</dt><dd>{{ log.status }}</dd>` の `<div>` を削除する。
残る `<dl>` は 日時 / 場所 / 飲み方 の3項目になる。`sm:grid-cols-2` のままでよい。

## 変更3: 「Google Maps」を Google マップへのリンクにする

`frontend/components/GoogleAttributions.vue` に**任意の `query` prop（string）**を追加する。

- `query` が非空のとき、先頭の `Google Maps` テキストを `<a>` にする。
  - `href`: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`
  - `target="_blank"` / `rel="noopener noreferrer"`
  - **緯度経度は一切使わない**（そもそも保存していない）。店名のみをクエリにする。
  - `translate="no"` と現在のクラスは維持する（Google のブランド表記要件）。
- `query` が未指定/空のときは**現在どおりプレーンテキスト**にする（後方互換）。

呼び出し側:
- `frontend/components/DrinkLogStoreDisplay.vue`: 表示している店名 (`displayName`) を渡す。
  ただし `場所登録済み` / `場所未登録` のプレースホルダのときは**渡さない**
  （検索語として無意味なため）。
- `frontend/pages/logs/new.vue` の近くの店候補リスト: `place.display_name` を渡す。

**ポリシー注意**: これは表示中の Google 名を検索クエリとしてリンクに載せるだけで、
`display_name` の**永続化ではない**。保存されるものは従来どおり `place_id` と
ユーザー入力の店名のみ。この不変条件を壊す変更をしないこと。

## 変更4: 日時を「撮影日時」にする（フロント + バックエンド）

### 4-1. フロント: EXIF から撮影日時を読む

新規 `frontend/utils/exifCapturedAt.ts`（`exifLocation.ts` と同じ流儀・同じ `exifr` 依存）:

```ts
/** 元ファイルの EXIF から撮影日時を読む。無い/不正なら null。 */
export const readExifCapturedAt = (file: File): Promise<string | null>
```

- `exifr.parse(file, ['DateTimeOriginal', 'OffsetTimeOriginal', 'CreateDate'])` 等で取得する
  （実際に使えるフィールド名は exifr の API を確認して決めること）。
- **オフセットの扱いを明示的に決める**: EXIF の `DateTimeOriginal` はタイムゾーンを持たない。
  `OffsetTimeOriginal` があればそれを採用し、無ければ**ブラウザのローカルタイムゾーン**として
  解釈する（撮影端末＝閲覧端末という前提。サーバーが勝手に UTC とみなすより実態に近い）。
- 返す文字列は**必ずオフセット付き RFC 3339**（`2026-08-01T21:30:00+09:00` 形式、または `Z`）。
- 妥当性チェック: 2000-01-01 より前、または**現在時刻 + 5分**より後は `null` を返す
  （壊れた EXIF がタイムラインの並び順を壊すのを防ぐ）。
- 例外は握って `null`（`readExifGps` と同じ fail-safe）。

`frontend/composables/useDrinkLogBatch.ts`:
- `DrinkLogBatchItem` に `capturedAt: string | null` を追加する。
- 処理フェーズ（`processItem`）で元ファイルから `readExifCapturedAt` を読み、item に保持する。
  **縮小後の Blob ではなく元ファイルから読むこと**（canvas 再エンコードで EXIF は失われる）。
- 保存時、`capturedAt` があれば作成ペイロードに `datetime` として載せる。
  無ければ**フィールドごと省略**する（サーバーが保存時刻を入れる従来動作）。

`frontend/composables/useDrinkLogs.ts`:
- `CreateDrinkLogPayload` に `datetime?: string` を追加。
- `DrinkLogFormValues` に `capturedAt?: string | null` を追加し、`buildDrinkLogPayload` が
  非空のときだけ `datetime` を載せるようにする（既存の任意フィールドと同じ書き方）。

`frontend/pages/logs/new.vue`:
- 各カードの `記録日時: 今（保存時刻）` を、撮影日時が読めたときは
  `撮影日時: {ローカル書式}`、読めなかったときは `記録日時: 保存時刻`（現行相当）に切り替える。
  書式は `frontend/utils/drinkLogs.ts` の `formatLocalLogDate` / `formatLocalLogTime` を再利用する。

`frontend/pages/logs/[id].vue`:
- 「日時」の値は `log.datetime` のままでよい（サーバー側で撮影日時が入るようになるため）。
  **ラベルだけ「日時」から「撮影日時」には変えない** — EXIF が無い記録では保存時刻が入るので、
  一律に撮影日時と名乗るのは不正確になる。ラベルは「日時」を維持すること。

### 4-2. バックエンド: 作成時に datetime を受け付ける

`lambda/drink-logs/index.py`:

- `CREATE_FIELDS` に `"datetime"` を追加する。**`UPDATE_FIELDS` には追加しない**
  （撮影日時は作成時にのみ確定する。PUT で GSI のソートキーを動かせるようにしない）。
- `validate_create_input` に検証を追加:
  - 文字列であること
  - **RFC 3339 かつオフセットまたは `Z` を持つこと。naive なタイムスタンプは 400 で拒否**
    （サーバーはクライアントの TZ を知り得ない）
  - 2000-01-01T00:00:00Z より前、または**現在時刻 + 5分**より後は 400
  - 検証を通ったら **UTC に正規化して `YYYY-MM-DDTHH:MM:SS.sssZ` 形式**にする
    （既存の `_rfc3339` / `_utc_now` と同じ字句順契約。GSI `UserDatetimeIndex` の
    ソートキーであり、形式が揺れると字句順↔時系列順の一致が壊れる）
- `_prepare_initial_record` が組み立てる pending レコードで、
  **`datetime` は検証済みの値があればそれを、無ければ `now` を使う**。
  **`created_at` / `updated_at` は常に実際の処理時刻（`now`）のまま**にすること
  （撮影日時で上書きしない — 監査・収束処理の根拠が壊れる）。
- 再開経路（`_finish_pending_create`）は既存 pending の `datetime` をそのまま使うこと
  （再試行で日時が動かない）。

### 4-3. ドキュメント

- `API_REFERENCE.md` の `POST /api/drink-logs` に任意 `datetime` を追記
  （オフセット必須・許容範囲・省略時はサーバー時刻）。
- `swagger.yml` の作成リクエストスキーマに `datetime` を追加。レスポンスの
  `datetime`（`Normalized RFC3339 UTC`）の記述は現状のままでよい。

---

## テスト

### `tests/lambda/test_drink_logs.py`

- 有効な `datetime`（`+09:00` 付き）を送ると、保存レコードの `datetime` が
  **UTC 正規化された値**になり、`created_at` / `updated_at` は処理時刻のままであること
- `datetime` 省略時は従来どおりサーバー時刻が入ること
- **naive なタイムスタンプ（`2026-08-01T21:30:00`）は 400** であること
- 未来（現在 + 1時間）と 1999 年は 400 であること
- `PUT /api/drink-logs/{id}` に `datetime` を送ると**受理されない**こと
  （`Field is not accepted` の 400）

### `frontend/tests/`

- `readExifCapturedAt`: オフセット付き EXIF、オフセット無し EXIF（ローカル TZ 解釈）、
  EXIF 無し、壊れた値、範囲外（未来・2000年より前）の各ケース。
  `exifr` はモックしてよい（実バイナリを置かないこと）。
- `buildDrinkLogPayload` が `capturedAt` を `datetime` として載せ、null/未指定なら
  **キーごと省略**すること
- `logsDetail.test.ts`: 「記録情報」トグルと「状態」項目が**存在しない**こと
- `GoogleAttributions`: `query` ありで `Google Maps` が期待 URL の `<a>`（`target="_blank"` +
  `rel="noopener noreferrer"`）になること、`query` なしでリンクにならないこと、
  クエリが URL エンコードされること
- `DrinkLogStoreDisplay`: プレースホルダ表示（`場所登録済み` / `場所未登録`）のときに
  `query` を渡さないこと

---

## 受入条件

- `python -m pytest tests` が全通過
- `cd frontend && npm ci && npm run lint && npm run typecheck && npx vitest run && npm run generate` が全通過
  （**`npm test` は watch モードなので使わない**）
- `cd infra && npm ci && npm run build && npx jest` が全通過（無変更のはずなので回帰確認）
- `git diff` に `infra/` が含まれないこと
- **`display_name` を永続化する経路が増えていないこと**（grep で確認）
- 緯度経度を保存・送信・URL 化する経路が存在しないこと
- 依存追加なし（`exifr` は既存依存）
