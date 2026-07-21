# Task 07b: create の手入力ブランド + 確認フォーム上書き対応

タスク07で `create` の受理フィールドが `{analysis_id, candidate_index}` のみ（`CREATE_FIELDS`、`lambda/drink-logs/index.py:51`）かつ candidate_index 必須のため、**2つのUXブロッカー**がある:
1. analyze が候補ゼロ（degrade。`lambda/drink-log-analyze/index.py:487` で `brand_candidates: []` を保存）だと、`candidate_index >= len(candidates)` で `AnalysisConflict` になり、**AIが銘柄を認識できない写真（グラス/ラベル無し等）は一切保存できない**。
2. 確認フォームで銘柄を手入力・店名/評価/メモ/飲み方を設定しても create が受け付けず、必ず create→PUT の2往復になる。

対象: `lambda/drink-logs/index.py`（create 経路のみ）、`tests/lambda/test_drink_logs.py`（追加）。**他ハンドラ・インフラ・analyze/places は変更しない**。タスク07の状態機械・原子性・カウンタ・画像サニタイズ・二段階削除は**そのまま維持**し、入力受理と AI 来歴消費の分岐のみ拡張する。

## 変更

### CREATE_FIELDS 拡張
`{analysis_id}`（必須）+ 任意 `{candidate_index, brand_text, serving_style, store, notes, rating}`。
- `analysis_id`: 必須（画像来歴の消費に常に使用 — user+s3_key+ETag+expires_at）。
- 検証: `analysis_id` は `ANALYSIS_ID_RE` 準拠。`candidate_index` は与えられた場合のみ非負int。ユーザー入力フィールドは既存 `validate_update_input`（`UPDATE_FIELDS` バリデータ）と**同一の検証**を再利用（`brand_text`≤200 / `store.name`≤200 + `place_id` 制約 / `notes`≤2000 / `rating` 既存基準 / `serving_style` enum）。

### AI 来歴消費の分岐（`_consume_analysis` / TransactWriteItems の Delete 条件）
- **candidate_index が指定された場合**: 既存どおり `#candidates[candidate_index] = :candidate` を含む条件で消費し、その候補から brand を導出。`whiskey_id` があれば `brand_source=matched`、無ければ `ai`。
- **candidate_index が無い場合（手入力/候補ゼロ）**: 消費の Delete 条件から `#candidates[...] = :candidate` 節を**外し**、`#user=:user AND s3_key=:s3_key AND #etag=:etag AND expires_at>:now_epoch` のみで ai-result を原子消費（**画像来歴は維持、AI銘柄主張だけ使わない**）。brand_source=`manual`、`whiskey_id` なし。
- **`brand_text` がリクエストにある場合**: candidate_index の有無に関わらず、最終 brand は**ユーザー入力で上書き**し `brand_source=manual`（ユーザーが編集した銘柄は AI 主張ではない）。candidate_index があっても消費は行う（画像来歴 + トークンの二重消費防止のため）。
- **serving_style/store/rating/notes がリクエストにある場合**: AI 由来値より優先してレコードに適用（ユーザー入力は AI 主張ではないので信用してよい）。無指定の場合は従来どおり ai-result 由来（serving_style は glass 検出結果、store は `{name:""}`）。

### 不変条件
- `datetime` は従来どおりサーバー側で now に正規化（この iteration ではクライアント指定不可 — タイムラインは保存時刻でグルーピング）。将来の過去日付対応は別タスク。
- 状態機械（pending→サニタイズ→complete→tmp削除）、カウンタ（日次create+生涯割当）、決定的ID、冪等再開、補償減算はすべて**タスク07のまま**。入力の受理と brand/来歴の分岐だけを変える。
- 空候補でも `analysis_id` の ai-result item は存在する（analyze が必ず put する）ので、手入力パスはそれを消費できる。

## テスト（追加）

- **候補ゼロの写真が手入力ブランドで保存できる**（analyze degrade → ai-result candidates=[] → create{analysis_id, brand_text:"自家製ハイボール"} → status complete、brand_source=manual、whiskey_id なし）。
- **候補選択 + brand_text 上書き** → brand_source=manual、消費は行われる（ai-result 削除、二重作成不可）。
- **候補選択のみ**（既存挙動、brand_source=ai/matched）が回帰しない。
- **確認フォーム上書き**（serving_style/store/rating/notes 指定）がレコードに反映される。
- **AI 来歴保護の維持**: candidate_index 指定時に ETag 不一致・期限切れ・候補改竄は従来どおり拒否。
- **手入力パスでも ETag/expires 束縛は維持**（差し替え画像・期限切れは拒否）。
- 既存の並行作成・応答喪失リトライ・障害注入テストが引き続き緑。

## 検証

`pytest tests/lambda/test_drink_logs.py tests/local_api/test_drink_logs_flow.py`（既存緑維持 + 新規）。`cd infra && npx jest`（infra 不変）。

## してはならないこと

- analyze/places/reconciler・インフラ・IAM・env・ルートの変更。状態機械/カウンタ/サニタイズ/削除ロジックの挙動変更（入力受理と brand/来歴分岐のみ）。reviews/ranking/list/search の変更。コミット作成。
