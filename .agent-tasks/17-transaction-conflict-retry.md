# Task 17: TransactWriteItems の TransactionConflict を再試行し、一括保存を直列化する

## 背景（本番で発生した実障害）

一括登録（写真N枚）で**1回目の保存が 500 で失敗**した。本番ログの事実:

```
08:57:19.267  POST /analyze  ┐ 1ms 差で同時
08:57:19.275  POST /analyze  ┘
08:57:20.089  TransactionCanceledException → 片方が 500

08:58:02.575  POST /api/drink-logs ┐ 1ms 差で同時
08:58:02.576  POST /api/drink-logs ┘
08:58:02.769  500  CancellationReasons=[None, None, None, TransactionConflict, None, None]
08:58:02.773  500  CancellationReasons=[None, TransactionConflict, TransactionConflict, None, TransactionConflict, None]
```

原因は2つ重なっている。

1. **フロントが保存を2件並列で走らせる**（`DRINK_LOG_BATCH_CONCURRENCY = 2`）。同一ユーザーの
   2件の保存は**必ず同じ AppState カウンタ item** を叩くため、衝突は偶発ではなく構造的。
   保存は1件200ms程度で、並列化の利得はほぼゼロ（10枚で約1秒）。
2. **`TransactionConflict` を再試行していない**。これは一過性エラーで再試行すれば解決するが、
   共有 boto3 設定は `total_max_attempts=2` かつ botocore はこの例外（400系）を自動再試行しない。
   さらに各呼び出し箇所の `except TransactionCanceledException` は `ConditionalCheckFailed`
   （＝上限到達・条件不成立）としてしか理由を解釈しておらず、`TransactionConflict` は
   どの分岐にも当たらず素の `raise` に落ちて **500** になる。

## スコープ

`lambda/` と `frontend/` の両方。**`infra/` は変更しない**（Lambda コードのみの変更で、
CDK のリソース定義・IAM・環境変数は一切変えない）。スキーマ・API 契約も変更禁止。

---

## 変更1: 共有レイヤーに再試行ヘルパーを追加

### 新規 `lambda/common/python/whiskey_common/transactions.py`

```python
def transact_write_with_retry(
    client,
    transact_items,
    *,
    max_attempts: int = 4,
    base_delay: float = 0.05,
    max_delay: float = 0.4,
    remaining_ms=None,   # Callable[[], int] | None — 残り実行予算(ms)を返す
    sleep=time.sleep,
    jitter=random.random,
) -> None
```

**振る舞いの契約（テストで固定すること）:**

- 成功するまで `client.transact_write_items(TransactItems=transact_items)` を呼ぶ。
- `TransactionCanceledException` を捕捉し `CancellationReasons` を検査する。
  - **1つでも `TransactionConflict` 以外の理由コードがある場合（`ConditionalCheckFailed` を含む）は
    即座に再送出する。再試行しない。** 上限到達や条件不成立は呼び出し側が意味づけしており、
    再試行すると費用上界の保証と所有権判定が壊れる。
  - 理由が `TransactionConflict` と `None`（＝理由なし）**のみ**で構成される場合に限り再試行する。
  - `CancellationReasons` が空の場合も再試行しない（意味が判定できないため fail-safe に再送出）。
- バックオフは **指数 + フルジッタ**: `sleep(min(max_delay, base_delay * 2**(attempt-1)) * jitter())`。
  固定間隔にしないこと（同時に落ちた2つが同じ間隔で再突入して再衝突する）。
- `max_attempts` 到達時は最後の例外をそのまま送出する（呼び出し側の既存分岐を壊さないため）。
- **予算認識**: `remaining_ms` が与えられた場合、次のスリープ + 200ms のマージンが残り予算を
  超えるなら再試行せず即座に送出する。analyze は API Gateway の 29 秒制約下にあるため必須。
- `time.sleep` / `random.random` は引数で差し替え可能にすること（テストを実時間に依存させない）。

`whiskey_common/__init__.py` の `__all__` にも公開する。

### 適用先（**全て**）

以下の `client.transact_write_items(TransactItems=...)` を `transact_write_with_retry(client, ...)` に置換する。
**既存の `except TransactionCanceledException` ブロックとその分岐は原則そのまま残す**
（再試行を尽くしても解決しなかった場合に従来の意味づけが働くため）。

| ファイル | 行（現状） | 備考 |
|---|---|---|
| `lambda/drink-logs/index.py` | 364 (`create_upload_url`) | |
| `lambda/drink-logs/index.py` | 644 (`_initial_create_transaction`) | 本障害の主経路 |
| `lambda/drink-logs/index.py` | 656 (`_compensate_pending`) | |
| `lambda/drink-logs/index.py` | 1172 (削除の収束) | |
| `lambda/drink-log-analyze/index.py` | 230 (`_reserve_analysis_budget`) | **`remaining_ms` を渡す**（下記） |
| `lambda/drink-log-analyze/places.py` | 276 | |
| `lambda/drink-logs/reconciler.py` | 240 | |

`grep` で `client.transact_write_items(` の直接呼び出しが**ヘルパー内以外に残っていないこと**を
受入条件に含める。

### analyze の予算連携

`_reserve_analysis_budget` は現在 `context` を受け取っていない。`index.py` の
`_remaining_budget_ms(context, started)` を利用できるよう、**呼び出し側から
`remaining_ms=lambda: _remaining_budget_ms(context, started)` を渡せるように引数を追加**する
（既存の呼び出し2箇所 — 627行付近と637行付近 — の両方を更新）。
引数を省略した場合は予算チェックなしで従来どおり動くデフォルトにすること。

---

## 変更2: 再試行を尽くした衝突を 500 にしない

`lambda/drink-logs/index.py` の `create_drink_log` は、キャンセル理由が
`TransactionConflict` のみだった場合に**どの分岐にも当たらず素の `raise`** に落ちて 500 になる
（963-974行）。これを修正する。

- 新しい例外 `TransientConflict(Exception)` を追加する。
- `create_drink_log` の `except TransactionCanceledException` の末尾、素の `raise` の直前で、
  **理由が `TransactionConflict` のみなら `TransientConflict` を送出**する。
- ハンドラ（1277行付近の `POST` 分岐）で捕捉し、**503** と
  `{"error": "書き込みが混み合っています。少し時間をおいて再試行してください。"}` を返す。
  `create_response(..., private=True)` の流儀は既存に揃える。
- `create_upload_url` の `except` は現在**全ての** `TransactionCanceledException` を
  `RateLimitExceeded` に変換しており（382行）、衝突が「1日の上限に達しました」という
  **嘘の 429** になる。ここも理由を検査し、`ConditionalCheckFailed` がある場合のみ
  `RateLimitExceeded`、`TransactionConflict` のみなら `TransientConflict` → **503** とすること。
- `drink-log-analyze/places.py:277-281` と `drink-log-analyze/index.py:231-238` は
  既に `ConditionalCheckFailed` のときだけ `BudgetExceeded` にしているので**意味づけは正しい**。
  再試行の追加のみでよい（枯渇時は従来どおり送出 → 500。ここは再試行で十分に守られる）。

---

## 変更3: フロントの保存フェーズを直列化

`frontend/composables/useDrinkLogBatch.ts`:

- `DRINK_LOG_BATCH_CONCURRENCY = 2` を**2つの定数に分割**する:
  - `DRINK_LOG_PROCESS_CONCURRENCY = 2` — 縮小・アップロード・解析。**並列を維持する**
    （Bedrock が1枚数秒かかるため並列化の利得が大きい）
  - `DRINK_LOG_SAVE_CONCURRENCY = 1` — 保存。**直列化する**
    （1件200ms程度で並列の利得がほぼ無い一方、同一ユーザーのカウンタ衝突を確実に起こすため）
- `processWithLimit` は `DRINK_LOG_PROCESS_CONCURRENCY`、`saveWithLimit` は
  `DRINK_LOG_SAVE_CONCURRENCY` を使う。
- **`DRINK_LOG_BATCH_CONCURRENCY` を参照している箇所が他にないか grep で確認**し、
  あれば適切な方へ振り分ける（テスト含む）。互換のための再エクスポートは残さない。
- 保存の直列化により、失敗時の per-item リトライ・部分成功の扱いなど既存の振る舞いは
  変えないこと（`savePending` の戻り値契約も不変）。

---

## テスト

### `tests/lambda/`（pytest）

新規 `tests/lambda/test_transactions.py`:
- `TransactionConflict` のみ → 再試行して2回目で成功する（`sleep` はスタブ、呼ばれた回数と
  スリープ時間が指数的に増えることを検証）
- `ConditionalCheckFailed` を含む → **1回で送出、再試行しない**
- `CancellationReasons` が空 → 再試行しない
- `max_attempts` 到達 → 最後の例外を送出
- `remaining_ms` が小さい → 再試行せず即送出（予算認識）
- ジッタが効いていること（`jitter` スタブの戻り値がスリープ時間に反映される）

既存の `tests/lambda/test_drink_logs.py` / `test_drink_log_analyze.py` に追加:
- **並行作成の衝突が最終的に成功する**: `transact_write_items` が1回目 `TransactionConflict`、
  2回目成功を返すモックで、`create_drink_log` が 500 相当の例外を投げずに完了すること
- **衝突が枯渇したら 503**: 常に `TransactionConflict` を返すモックで `TransientConflict` が
  送出され、ハンドラ経由で **status 503** になること（500 でないことを明示的に検証）
- **上限到達は従来どおり 429**: `ConditionalCheckFailed` を含む理由では `RateLimitExceeded` →
  429 のまま、かつ**再試行が行われていないこと**（呼び出し回数1回）を検証
- `create_upload_url` の衝突が **429 ではなく 503** になること（嘘の 429 の回帰防止）

### `frontend/tests/`（vitest）

`tests/composables/useDrinkLogBatch.test.ts`:
- **保存が直列であること**: `createLog` の解決を保留させ、3件の item で `savePending()` を呼び、
  同時に in-flight な `createLog` が**常に1件以下**であることを検証
- **処理は並列のままであること**: 同様の手法で `analyze`（または `getUploadUrl`）の同時
  in-flight が2件に達することを検証
- 既存の部分失敗・per-item リトライのテストが緑のままであること

---

## 受入条件

- `python -m pytest tests` が全通過。
- `cd frontend && npm ci && npm run lint && npm run typecheck && npx vitest run && npm run generate` が全通過
  （**`npm test` は watch モードなので使わない**）。
- `cd infra && npm ci && npm run build && npx jest` が全通過（CDK は無変更のはずなので回帰確認）。
- `git diff` は `lambda/` `frontend/` `tests/` `.agent-tasks/` のみ。**`infra/` に一切触れていない**。
- ヘルパー外に `transact_write_items(` の直接呼び出しが残っていない（grep 検証）。
- **費用上界の保証が変わっていないこと**: `ConditionalCheckFailed` は一度も再試行されない。
- 依存追加なし（`time` / `random` は標準ライブラリ）。

## 実装メモ

- 再試行は「同時に落ちた両者が同じタイミングで再突入する」のを避けるためフルジッタが要る。
  固定バックオフや等間隔リトライは不可。
- `max_attempts=4` / `base_delay=0.05` / `max_delay=0.4` なら最悪でも累積1秒未満で、
  drink-logs の25秒予算にも analyze の24秒予算にも収まる。
- ローカルアダプタ（`local_api/`）は Lambda ハンドラを import するだけなので変更不要のはず。
  もし import 経路の都合で変更が要るなら最小限に留めること。
