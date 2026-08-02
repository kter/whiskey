# Task 29: 解析結果にブランド/蒸留所を持たせ、カタログのブランド層を拡充する

## 背景

実写真27枚で評価セットを作った結果、採点軸の構造的な欠陥が判明した。

| 照合の層 | 命中 |
|---|---|
| エクスプレッション（現行の `expected_whiskey_id`） | **8/27** |
| ブランド / 蒸留所 | **15/27** |

ウイスキーは**閉じた集合（蒸留所・ブランド）**と**開いた集合（エクスプレッション）**が
混在している。エクスプレッションは毎年の限定品やボトラーズで無限に増え続けるため、
カタログを完成させることが原理的にできない。一方ブランド/蒸留所は数えられる。

ブランド層で外れた10件は**すべて「カタログ未登録の蒸留所」**であり、10行足せば 27/27 になる。
同じ範囲をエクスプレッション層で埋めようとすると「立春」「Piscas」
「インチファッド 2005 17年」のような**二度と出てこない一品**を個別登録することになる。

`scripts/catalog/brands.json` は既に `brand_key` / `aliases` / `distillery_ja` / `distillery_en`
を持ち、`expressions.json` は `bottler` / `vintage` / `edition` を持っている。
**2層構造は既にあるが、使われていない。** 理由は `lambda/drink-log-analyze/index.py` が
フラットな名前文字列しか返さないためで、しかも検証が
`set(whiskey) != {"name_ja","name_en","confidence"}` と厳格なので拡張もできない。

**モデルが出力しないものは測れない。** ここが詰まりどころなので、まず解析の出力を広げる。

## スコープ

`lambda/drink-log-analyze/` `scripts/catalog/` `frontend/composables/useDrinkLogs.ts`
（型のみ）と各テスト。**`infra/` は変更しない。**
**`lambda/drink-logs/` の作成経路のロジックは変更しない**（下記の互換性の項を厳守）。
評価ハーネス側の採点軸変更は**別タスク**で行う。

---

## 変更1: 解析にブランド/蒸留所を返させる

`lambda/drink-log-analyze/index.py`:

- プロンプトの出力例（63-67行付近）に **`brand`** を追加する。
  `{"whiskeys":[{"name_ja":"カリラ 12年","name_en":"Caol Ila 12 Year Old",
  "brand_ja":"カリラ","brand_en":"Caol Ila","confidence":0.95}], ...}`
- **`brand_ja` / `brand_en` の定義をプロンプトで明示すること**:
  「蒸留所またはブランドの名前だけ。熟成年数・カスク・限定表記・`シングルモルト` 等の
  種別語は含めない」。621 の指摘どおり、ラベルで一番大きい文字が蒸留所名である場合も
  あるため、「ラベルの最大文字」ではなく「蒸留所/ブランド」を求めていると明記する。
- 検証（276行付近）の厳格な集合一致を
  `{"name_ja","name_en","confidence"}` に加えて **`brand_ja` / `brand_en` を任意で許可**する形に
  広げる。**未知のキーは従来どおり拒否**すること（厳格さは捨てない）。
  型と長さの検査は既存の name_ja/name_en と同じ基準（str・200字以内）。
- `brand_ja` が空文字や欠落の場合は、**degrade して従来どおり動く**こと。
  モデルが返さなくても解析全体が失敗してはならない。

## 変更2: 候補にブランド情報を載せる

`_build_candidates`（577行付近）が返す候補に以下を追加する。

- `brand_ja` / `brand_en`: モデルの読み取り（無ければキーごと省略）
- `brand_key`: **カタログのブランド層と照合できた場合のみ**。照合は
  `brands.json` の `brand_ja` / `brand_en` / `aliases` を正規化して行う
  （既存の `_catalog_match` と同じ正規化ヘルパーを使うこと。新しい正規化を書かない）
- `distillery_ja`: `brand_key` が決まった場合のみ、カタログの値を入れる

**エクスプレッション照合（`whiskey_id`）の既存ロジックは変更しない。**
ブランド照合は独立に行い、`whiskey_id` が付かなくても `brand_key` は付きうる
（これが本タスクの目的そのもの）。

### 互換性の厳守事項

`lambda/drink-logs/index.py` の `create_drink_log` は、AI 結果を消費するとき
`ConditionExpression` に `#candidates[i] = :candidate` を使い、**保存済み候補との完全一致**を
要求する。比較対象は AppState に保存された候補オブジェクト同士なので、
候補にキーが増えること自体は安全だが、以下を守ること。

- **`_completion_from_analysis` と `create_drink_log` のロジックを変更しない。**
  ブランド情報を DrinkLog レコードに永続化するかどうかは**別の判断**であり、
  本タスクではやらない。
- 既存のテスト（`tests/lambda/test_drink_logs.py`）が緑のままであること。
- デプロイ時に AppState に残っている**旧形式の候補**が消費されても壊れないこと
  （create は保存済みオブジェクトをそのまま読むので影響しないはずだが、テストで固定する）。

## 変更3: カタログのブランド層に10件追加

`scripts/catalog/brands.json` に以下を追加する。既存エントリと同じフィールド構成
（`brand_key` / `brand_ja` / `brand_en` / `aliases` / `distillery_ja` / `distillery_en` /
`region` / `country`）に揃えること。

| brand_key | brand_ja | brand_en | 蒸留所 | 地域 |
|---|---|---|---|---|
| `akkeshi` | 厚岸 | Akkeshi | 厚岸蒸溜所 / Akkeshi Distillery | Japan |
| `sakurao` | 桜尾 | Sakurao | 桜尾蒸留所 / Sakurao Distillery | Japan |
| `shizuoka` | 静岡 | Shizuoka | ガイアフロー静岡蒸溜所 / Gaiaflow Shizuoka Distillery | Japan |
| `yuza` | 遊佐 | Yuza | 遊佐蒸溜所 / Yuza Distillery | Japan |
| `ichiros-malt` | イチローズモルト | Ichiro's Malt | 秩父蒸溜所 / Chichibu Distillery | Japan |
| `kilchoman` | キルホーマン | Kilchoman | キルホーマン蒸留所 / Kilchoman Distillery | Islay |
| `port-charlotte` | ポートシャーロット | Port Charlotte | ブルックラディ蒸留所 / Bruichladdich Distillery | Islay |
| `loch-lomond` | ロッホ・ローモンド | Loch Lomond | ロッホ・ローモンド蒸留所 / Loch Lomond Distillery | Highlands |

**`aliases` には表記揺れを入れること。** 621 の指摘②への対応であり、ここが効く。
例: `akkeshi` → `["厚岸", "アッケシ", "Akkeshi"]`、
`port-charlotte` → `["ポートシャーロット", "ポート・シャーロット", "Port Charlotte"]`、
`ichiros-malt` → `["イチローズモルト", "イチローズ・モルト", "Ichiro's Malt", "Ichiros Malt"]`、
`loch-lomond` → `["ロッホ・ローモンド", "ロッホローモンド", "Loch Lomond", "インチファッド", "Inchfad"]`。

**残る2件は事実が確認できないため、このタスクでは追加しない。**
`マクリハニッシュ モア` と `大谷ウイスキー 新潟亀田`（蒸溜所名は「新潟亀田蒸溜所」と
ラベルにあるが、ブランドとの関係が未確認）。**推測でエントリを作らないこと。**
不足として残す旨を作業報告に明記する。

`scripts/catalog/expressions.json` は**変更しない**。エクスプレッション層を追いかけない
というのが本タスクの主旨である。

## 変更4: フロントの型

`frontend/composables/useDrinkLogs.ts` の `DrinkLogCandidate` に
`brand_ja?` / `brand_en?` / `brand_key?` / `distillery_ja?` を任意で追加する。
**UI の表示は変更しない**（別途デザインの判断が要る）。型だけ通す。

---

## テスト

### `tests/lambda/test_drink_log_analyze.py`

- `brand_ja` / `brand_en` を含むモデル応答が受理され、候補に載ること
- **`brand_ja` が欠落した応答でも解析が成功する**こと（degrade）
- 未知のキーを含む応答は従来どおり**拒否**されること
- ブランド照合が `aliases` 経由で成立すること（例: 「アッケシ」→ `akkeshi`）
- **`whiskey_id` が付かないケースでも `brand_key` は付く**こと（本タスクの核心）
- `brand_key` が決まらない場合は `brand_key` / `distillery_ja` がキーごと無いこと

### `tests/lambda/test_drink_logs.py`

- 既存テストが緑のまま
- **ブランド情報を含む候補を消費して作成が成功する**こと
- **旧形式（ブランド情報なし）の候補を消費しても成功する**こと

## 受入条件

- `python -m pytest tests` が全通過
- `cd frontend && npm run lint && npm run typecheck && npx vitest run && npm run generate` が全通過
- `git diff` に `infra/` が含まれないこと
- `lambda/drink-logs/index.py` の `create_drink_log` / `_completion_from_analysis` が無変更
- `scripts/catalog/expressions.json` が無変更
- 依存追加なし
- **事実が確認できない蒸留所を推測で書かないこと**
