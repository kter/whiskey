# Task 07: drink-logs CRUD Lambda 本体 + リコンサイラ本体

タスク06の 501/noop スタブを実装で置換する。対象: `lambda/drink-logs/index.py`（CRUD+presign）、`lambda/drink-logs/reconciler.py`（日次収束）、`tests/lambda/test_drink_logs.py`（新規）。**インフラ（テーブル/バケット/IAM/ルート/env）はタスク06で確定済み・変更しない**。画像正規化の共有関数 `whiskey_common/images.py` は**タスク08で新設**するが、**タスク07も同じサニタイズを行う** → タスク08と重複しないよう、このタスクで `lambda/common/python/whiskey_common/images.py` を新設し（下記§画像正規化）、両タスクが共有する。タスク08はそれを import する前提。

前提の正典: `docs/COST_MATRIX.md`（上限値）、タスク06の env 変数・AppState プレフィックス（`drinklog-counter#*` / `drinklog-quota#*` / `ai-result:*`）。既存の実装パターンは `lambda/reviews/index.py` に倣う（`_rate_counter_update` :209 = `pk`キー・`#count < :limit`条件・TTL付き ADD、`transact_write_items` :288、所有権 `ConditionExpression #owner = :caller` :338）。共有レイヤーの `whiskey_common`（responses.create_response(event=,private=), logger, clients, jwt_utils, normalize）を使う。

## 認証・識別

全ルートは API GW Cognito authorizer 済み（タスク06）。ハンドラは `event.requestContext.authorizer.claims` から `sub`/`aud`/`token_use` を取得し、**`aud == COGNITO_CLIENT_ID` かつ `token_use == 'id'` を Lambda 側で再検証**（多層防御、reviews と同方針）。ローカルアダプタの MOCK 注入 claims でも成立すること。

## 画像正規化 `whiskey_common/images.py`（新設・共有）

安全順序を厳守した関数 `normalize_image(raw: bytes, *, max_bytes: int) -> bytes` を実装:
1. **ヘッダーから寸法検査**（`Image.open` で `.size` のみ参照、`load()` 前）: 総 20MP 超 または 1辺 8000px 超は `ImageTooLargeError` を送出（デコード爆弾を展開しない）。
2. デコード → `ImageOps.exif_transpose`（EXIF 方向を適用してから方向情報を捨てる。先に EXIF を捨てると回転が壊れる）。
3. アルファ/CMYK/P → RGB フラット化。
4. 必要なら縮小（長辺 ~1600px 目安）。
5. **メタデータなし JPEG 再エンコード**（`exif`/`icc_profile` を渡さない = GPS 含む EXIF 全除去）。バイト超過時は quality を段階的に下げ、それでも `max_bytes`(1.5MB) 超なら寸法を段階縮小。到達不能なら `ImageEncodeError`。
6. マジックバイト検証ヘルパー `sniff_format(raw) -> 'jpeg'|'png'|'webp'|None` も提供（HeadObject では本文が無いので `get_object(Range=bytes=0-15)` のバイトを渡す用途）。HEIC 等は None。
- テストベクタ: 回転付きJPEG（Orientation 6）・透過PNG・WebP・20MP超・8000px超・1.5MB到達不能。タスク06/08 の両 requirements に Pillow は既に固定同梱済み。

## upload-url（`POST /api/drink-logs/upload-url`）

- body: `content_type` ∈ {`image/jpeg`,`image/png`,`image/webp`}（**HEIC は 400 で明示拒否**）。
- **日次アップロード上限を原子的条件付き更新で消費**（`_rate_counter_update` 相当、キー `drinklog-counter#upload#user#{uid}#{utc_date}` と `#global#{utc_date}`、TTL 2日、超過は 429）。
- **presigned POST** 生成: `Fields`/`Conditions` に `Content-Type` 固定 + **`content-length-range` 0〜`UPLOAD_MAX_BYTES`(3.5MB)** + キー `tmp/{uid}/{uuid}.{ext}`、**有効期限120秒**。返却: `upload_url`, `fields`, `s3_key`。
- 脅威モデル注記コメント: 取得済み POST はキー単一固定のため再利用は同一オブジェクト上書きのみ、ストレージ/高額API消費なし。残余は期限窓内 PUT 課金（上界なし・低単価・アラーム監視）。

## analyze 結果の参照（タスク08と契約）

create は AI メタデータを**クライアントから信用しない**。body は `analysis_id`（= AppState の `ai-result:{uid}:{s3_key_uuid}` を指すトークン）+ 候補 index のみ受け取り、**§create ① の TransactWriteItems 内で `ai-result:*` item を条件付き消費**（後述）。結果 item のスキーマ（user・s3_key・ETag・候補配列・serving_style・model_id・confidence・matched whiskey_id・`expires_at`）はタスク08が定義・保存。タスク07はそれを**読んで照合・消費**する側。

## create（`POST /api/drink-logs`）— 状態機械（補償削除なし）

**レコードID = 決定的導出**: `uuidv5(NAMESPACE_DRINKLOG, f"{caller_uid}\0{upload_uuid}")`（`upload_uuid` は s3_key から抽出）。**Python 組み込み `hash()` は禁止**（プロセス毎に変わる）。別プロセスで同一IDになるテスト必須。UUID単独由来にしない（他人の既知UUID埋め込み衝突を防ぐため caller_uid を必ず混ぜる）。

手順:
- **⓪ 冪等性チェック**: `GetItem(ConsistentRead=True)` で既存レコード確認。存在すれば `existing.user_id == caller` を全分岐の前提（不一致は404）。`status==complete` → 200即返却（**image_url 付き = 所有者検証済みの場合のみ**新規 presigned GET を発行）。`status==pending` かつ同一所有者 → ② から再開。**いずれもクォータを再消費しない**（応答喪失リトライの二重課金防止）。
- **① 初回のみ TransactWriteItems**（`attribute_not_exists(id)` 成立時）:
  - (a) `status=pending` レコードの条件付き Put（`attribute_not_exists(id)`）。フィールド検証済みの入力 + `tmp_s3_key`、`quota_allocated=true`、`datetime`（RFC3339 UTC 正規化）、`s3_image_key` は未確定（pending 中は tmp を指すか空）。**TTL は付けない**。
  - (b) 日次 create カウンタ消費（user/global、`drinklog-counter#create#...`、TTL 2日、`#count < :limit`）。
  - (c) **生涯=現在割当カウンタ消費**（user/global、`drinklog-quota#user#{uid}` / `#global`、**TTL なし**、`#count < :limit`、`STORAGE_USER_LIMIT`/`STORAGE_GLOBAL_LIMIT`）。
  - (d) **AI 結果を使う場合のみ**: `ai-result:{uid}:{uuid}` item の **Delete に ConditionExpression**（`user`・`s3_key`・`ETag`・候補一致 + `expires_at > now`）を統合して原子消費。**同一 item への ConditionCheck+Delete 併記は TransactWriteItems 仕様違反 → Delete に条件を載せる**。期限切れ/不成立は再解析要求（409/該当エラー）。
  - `TransactionCanceledException` 時は勝者レコードを `ConsistentRead=True` で再読し complete 応答 or pending 再開へ収束（⓪ に合流）。カウンタ理由（limit 超過）は 429。
- **② サニタイズ書き込み**: `get_object(tmp_s3_key, IfMatch=検証時ETag)` で取得 → `sniff_format` で実形式検証（宣言と不一致は 400 でクリーンアップ）→ `normalize_image(raw, max_bytes=IMAGE_MAX_BYTES)` → **最終キー = 試行固有 `logs/{uid}/{uuid}-{attempt}.jpg`** に `put_object`（`Content-Type: image/jpeg`, `CacheControl: private, no-store`, メタデータなし）。
- **③ complete 遷移**: `status=pending` 条件付き `update_item` で**勝者の試行キーだけ**を `s3_image_key` に採用（`status=complete`, `ai.*`/`brand_source` 設定, `updated_at`）。敗者試行オブジェクトは孤児 → リコンサイラ回収対象。
- **④ tmp 削除**: `s3_image_key` は既に logs キーに置換済みのため、`tmp_s3_key` 属性を保持したまま tmp を delete → 削除確認後に `tmp_s3_key` を REMOVE。③後④前クラッシュはリコンサイラが tmp/ 走査で回収。
- **サニタイズ終端的失敗**（デコード不能・画素超過で縮小不能・1.5MB到達不能）: `pending 削除 + 生涯割当カウンタ減算` を同一 TransactWriteItems で補償（日次カウンタは返金なし）。400 + フィールドエラー。
- レスポンス: complete レコード + `image_url`（presigned GET, 15分, `ResponseCacheControl` 上書き）。

**テスト必須**: 並行作成（一方勝ち/敗者カウンタ非消費）・応答喪失リトライ（二重課金なし・200再応答）・各ステップ障害注入（画像/レコード最終収束）・決定的ID同一性・AI結果 ETag/候補束縛消費・PNG/WebP入力の create→GET→DELETE 通し。

## timeline GET（`GET /api/drink-logs`）

- `UserDatetimeIndex` 降順 Query、`next_token` ページネーション。
- **ページ充填ループ**（pending/deleting 除外 + brand/store/place_id フィルタは FilterExpression → 「limit指定Query 1回」では空ページで打ち切る）: 内部ページを上限付きで反復し limit 充足 or 走査終了まで進め、途中状態を next_token にエンコード（タスク03d の検索と同方式）。
- フィルタ契約: `store`=ユーザー入力店名テキストへのフィルタ、`place_id`=完全一致、別パラメータ。`limit ≤ 50`、フィルタ文字列 ≤100字。
- 各アイテムに presigned GET `image_url`（**`status==complete` かつキーが `logs/{uid}/` 配下のみ**。pending/deleting には URL を返さないテスト）。
- レスポンスに **`Cache-Control: private, no-store`**（共通ヘルパー、個人データ+presigned URL）。

## detail / update / delete（`/{id}`）

- 所有権は **`ConditionExpression user_id = :caller`** で原子強制（他人のは404、read-then-write 禁止）。
- **update**: `id`/`user_id`/`s3_image_key`/`created_at` は不変（許可フィールドのホワイトリスト方式で拒否）。`status==complete` のみ更新可。入力検証: `brand_text`≤200 / `store.name`≤200 / `place_id` 印字可能ASCII≤1000 / `notes`≤2000 / `rating` 既存レビュー同基準 / `serving_style` enum。`place_id` は候補選択でのみセット・選択解除でクリア、店名編集は place_id 維持。
- **delete = 二段階 + リコンサイラ収束**: ① `status=deleting` 条件付き update（TTL 付けない、タイムラインから消える）→ ② S3 削除 → ③ **レコード削除 + 生涯割当カウンタ減算を同一 TransactWriteItems で一度だけ**（`quota_allocated=true` 条件）。②③失敗は次回削除呼び出しで再開、最終的にリコンサイラが収束。**S3削除確認前にレコードを消さない**。

## リコンサイラ `reconciler.py`（本体）

日次。`RECONCILE_AGE_HOURS`(48) 超を対象。全て **fail-closed**（ConsistentRead 照合、BatchGet UnprocessedKeys 有限リトライ、S3/DynamoDB とも全ページ走査、読み取りエラー/未確認オブジェクトは絶対削除しない）:
- ① `logs/` 全走査: 48h超で「対応レコードなし or status≠complete」→ レコードありは条件付き `pending→deleting` 獲得後 S3 削除。レコード不存在は `attribute_not_exists(id)` 条件で `deleting` tombstone（**`quota_allocated=false` 明示**）作成後 S3 削除（作成側の条件付き put と排他）。**照合はレコードの `s3_image_key` 一致で判定**（敗者試行キーは対象）。
- ② `status=deleting` レコード: S3 削除 + レコード削除完遂。`quota_allocated=true` のみ減算（条件付きトランザクション）。
- ③ 48h超 `pending`（copy未達）: 条件付き獲得で削除 + `quota_allocated` に基づき割当カウンタ返金（同一トランザクション）。
- ④ `tmp/` 全走査: 48h超で `tmp_s3_key` 参照が残らない tmp を削除（ライフサイクル任せにしない明示掃除）。
- ⑤ `status=complete` かつ `tmp_s3_key` 保持（complete後・tmp削除前クラッシュ）: tmp 削除 → 不在確認 → `tmp_s3_key` REMOVE。
- 各ステップ後クラッシュ・障害注入で「画像・レコードとも最終収束」となるテスト必須。

## 検証

`pytest tests/lambda/test_drink_logs.py tests/local_api/test_main.py`（moto[dynamodb] + S3 は moto または stub）。`cd infra && npx jest`（既存グリーン維持 — このタスクは infra を変えないので影響なしを確認）。ローカルアダプタは analyze/create の MOCK 経路で通ること（実 analyze はタスク08、ここは 501 のままでよいが drink-logs 本体ルートは実装）。

## してはならないこと

- インフラ（テーブル/バケット/IAM/ルート/env/Scheduler）の変更（タスク06確定）。
- analyze/places ハンドラ本体（タスク08）。ただし `images.py` は本タスクで新設し両者共有。
- reviews/ranking/list/search の変更。実AWSアクセス、コミット作成。
- Bedrock/Places シークレットのハードコード。GPS 座標(lat/lng)の DrinkLogs 保存、Google 表示名の永続化。
