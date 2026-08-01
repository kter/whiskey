# Task 16: 銘柄候補セレクトの廃止 / 店を写真ごとに / 文言の刷新

## 背景・スコープ
実機利用のフィードバック3件。**フロントエンドのみ**（`frontend/` 配下）で対応する。
`lambda/`・`infra/`・スキーマ・API 契約（リクエスト/レスポンス JSON の形）は一切変更禁止。
`git diff` が `frontend/` 以外に触れていたら不合格（`.agent-tasks/` を除く）。

対象ファイル（想定）:
- `frontend/composables/useDrinkLogBatch.ts`
- `frontend/pages/logs/new.vue`
- `frontend/pages/logs/index.vue`
- `frontend/pages/home.vue`
- `frontend/pages/privacy.vue`
- `frontend/tests/composables/useDrinkLogBatch.test.ts`
- `frontend/tests/pages/logsNew.test.ts`
- `frontend/tests/components/imageLightbox.test.ts`（alt 文言のみ）

---

## 変更1: AI 銘柄候補のセレクトボックスを廃止する

### 現状の問題
`new.vue` の確認カードにある `<select>`（`AIの銘柄候補`）は、実際には候補が1件しか返らない
ことがほとんどで、選択肢は「候補を使わず手入力」＋候補1件だけになる。そのすぐ下に
「銘柄名 *」の自由入力欄があり、手入力はそちらで完結するため、このセレクトは意味を持たない。

### あるべき姿
セレクトを削除し、候補数に応じて表示を出し分ける。

- **候補0件**: 現行の注記をそのまま維持
  「銘柄候補を特定できませんでした。下の銘柄名を手入力してください。」
- **候補1件**: コントロールを置かない。`applyAnalysis` が既に `brandText` を埋めているので、
  「銘柄名 *」入力欄の下に**読み取り結果の注記**を出すだけにする。文言:
  `AIの読み取り: {brand_text}（確度 {confidence*100 の四捨五入}%・{match_source === 'catalog' ? 'カタログ一致' : 'AI読取'}）`
- **候補2件以上**: `<select>` ではなく**チップ（ボタン）で選ばせる**。既存の「飲み方」ピル
  （`SERVING_STYLES` の `rounded-full border px-3 py-1.5` なラベル群）と同じ視覚言語に揃える。
  - 各チップのラベルは `{brand_text}（{確度}%）`。選択中はピルと同じ選択状態スタイル
    （`border-amber-500 bg-amber-700 text-amber-100`）、非選択は（`border-stone-500 bg-stone-600 text-amber-300`）。
  - `type="button"`。クリックで既存の `selectCandidate(item, index)` を呼ぶ。
  - 見出しは `AIが検出した銘柄`。既存の警告注記
    「複数のボトルを検出しました。記録する銘柄を選んでください。」は維持する。
  - `item.saveStatus === 'saved'` のときは `disabled`。
  - **選択解除の専用 UI は作らない** — 銘柄名欄を編集すれば `handleBrandInput` 経由で
    `selectedCandidateIndex` が null になる（既存挙動）。この経路が壊れていないことをテストで担保する。

### 状態の整理
`candidateSelection: string` は `<select>` の v-model 専用フィールドなので、
**`DrinkLogBatchItem` から完全に削除**する（`newItem` の初期値・`processItem` のリセット・
`applyAnalysis` の代入・`new.vue` の `handleCandidateSelection`・テストの参照をすべて削除）。
`selectedCandidateIndex` は保存ペイロードの `candidate_index` を決める本体なので**残す**。

`handleCandidateSelection` は不要になるため削除。`selectCandidate` / `handleBrandInput` は残す。

### 壊してはいけない契約
- `buildDrinkLogPayload` は `candidateIndex === null` のとき `brand_text`、そうでなければ
  `candidate_index` を送る。**この分岐と送信 JSON の形は変えない**。
- 候補1件が自動選択される（`applyAnalysis` の既存挙動）ことで、ユーザーが何もしなければ
  `candidate_index: 0` が送られ `brand_source` が `ai|matched` になる。**この挙動を維持**する。

---

## 変更2: 店（場所）を写真1枚ごとに選べるようにする

### 現状の問題
店は「全ての記録に共通の店」セクションでバッチ全体に1つだけ選ぶ形になっており、
`savePending(storeName, placeId)` で全カードに同じ値が適用される。
複数枚をまとめて登録できるのに、写真ごとに違う店を記録できない。

### あるべき姿
**店の状態をカード（＝1杯）ごとに持つ。** 位置情報の取得と店候補の検索は共通のまま。

#### `useDrinkLogBatch.ts`
- `DrinkLogBatchItem` に `storeName: string` と `placeId: string` を追加（初期値は空文字）。
  `newItem` で初期化し、`processItem` の再処理リセットでは**クリアしない**
  （再解析でユーザーが選んだ店を消さないため。他のユーザー入力と違い店は写真から導出されない）。
  ※ ただし `processFiles` は `reset()` で items ごと作り直すので新規選択時は自然に空に戻る。
- `saveItem(item)` / `retrySave(item)` / `savePending()` から `storeName` / `placeId` 引数を削除し、
  `item.storeName` / `item.placeId` を使う。**呼び出し側の署名変更をテストにも反映**すること。
- 保存ペイロードは従来どおり `buildDrinkLogPayload` に `storeName` / `placeId` を渡す。
  **API 契約は不変**。

#### `new.vue`
- ページレベルの `storeName` / `selectedPlaceId` ref は削除する。`places` / `placeError` /
  `placeNotice` / `findNearbyPlaces` / `searchNearbyPlaces` / EXIF 連携は**共通のまま維持**。
  - `searchNearbyPlaces` 内の `selectedPlaceId.value = ''` は、**全 item の `placeId` を空にする**
    処理へ置き換える（新しい候補集合に対して古い place_id が残るのを防ぐ）。
    `storeName` は消さない（ユーザーが手入力した店名は候補の再検索で失われるべきでない）。
- 共通セクションの見出しを `店を探す` に変更し、説明文を
  「近くの店を検索して、写真ごとに店を選べます。」に更新。位置情報の同意文言（`disclosure`）と
  「近くの店を探す」ボタン、`placeNotice` / `placeError` はそのまま残す。
- **候補一覧（現在のラジオリスト）は共通セクションに「参照用の一覧」として残す**。
  ラジオ入力は削除し、店名・住所・`<GoogleAttributions>` を表示するだけのリストにする
  （Google の表示名を出す箇所には帰属表示が必要なため、一覧側で必ず帰属を描画する）。
  見出しは `近くの店候補`。
- 共通セクションに **「1杯目の店を全カードに適用」ボタン**を置く（`items` に ready なカードが
  2件以上あるときのみ表示）。押すと1件目の `storeName` / `placeId` を他の全カードへコピーする。
  `saveStatus === 'saved'` のカードは対象外。
- **各確認カードに店の入力を追加**する（「ノート（任意）」の直前あたり）:
  - `店（任意）` の `<select>`：`places` が空でなければ表示。
    `<option value="">店を選ばない</option>` ＋ 各候補（ラベルは `display_name`）。
    v-model は `item.placeId`、`:disabled="item.saveStatus === 'saved'"`。
    id は `place-${item.id}` のように**カードごとに一意**にすること。
  - 選択中の候補があれば、その `<GoogleAttributions :attributions="place.attributions" />` を
    セレクトの直下に描画する。
  - `記録に残す店名（任意）` のテキスト入力：v-model は `item.storeName`、`maxlength="200"`、
    id は `store-name-${item.id}`。
  - 注記「Googleの表示名は保存しません。選んだ店の place_id と、ここに入力した名前だけを保存します。」を
    カード側へ移す（共通セクションからは削除）。
- `handleSubmit` は `savePending()`、`handleSaveRetry(item)` は `retrySave(item)` を呼ぶ形に更新。

### 壊してはいけない契約（**最重要**）
- **GPS 座標（lat/lng）は保存もペイロード送信もしない**。EXIF/端末 GPS で得た座標は
  Places 検索に渡した直後に破棄する現行実装を維持すること。
  `frontend/tests/pages/logsNew.test.ts` の
  「保存呼び出しの引数に緯度経度が含まれない」旨のテストは、**新しい署名に合わせて書き換えたうえで
  必ず残す**（`item.storeName` / `item.placeId` にも座標が入らないことを検証する形にする）。
- 店名はユーザー入力テキスト、`place_id` は場所参照、という役割分担は不変。
  **Google の `display_name` を `storeName` に自動代入してはならない**（ポリシー要件）。

---

## 変更3: 文言の刷新（「飲酒〜」を「テイスティング記録」系へ）

「フォトファースト飲酒ログ」「飲酒ログ」「飲酒タイムライン」が不自然なので置き換える。
**採用する語彙は以下で確定済み。勝手に別案を作らないこと。**

| 箇所 | 旧 | 新 |
|---|---|---|
| `pages/home.vue:10` 上部ラベル | フォトファースト飲酒ログ | 写真ではじめるテイスティング記録 |
| `pages/logs/new.vue` 上部ラベル | フォトファースト飲酒ログ | 写真ではじめるテイスティング記録 |
| `pages/logs/index.vue` h1 | 飲酒タイムライン | テイスティング履歴 |
| `pages/privacy.vue:25` | 保存した飲酒ログ画像 | 保存したテイスティング記録の画像 |
| `pages/logs/new.vue` の画像 alt / lightbox alt | `{n}杯目の飲酒記録写真` | `{n}杯目のテイスティング写真` |

- `pages/terms.vue:13` の「飲酒体験」「飲酒は法令を守り」は**変更しない**
  （法務的な文脈で「飲酒」が適切なため）。
- 上表以外の場所に新たな言い換えを持ち込まないこと。`飲み方` `一杯` `記録` 等の既存語は維持。
- alt 文言を変えたテストの期待値（`tests/pages/logsNew.test.ts` / `tests/components/imageLightbox.test.ts`）も
  合わせて更新する。

---

## テスト（vitest, `frontend/tests/`）
既存テストを新しい署名・DOM に追従させたうえで、**次を新規に追加**すること。

`tests/composables/useDrinkLogBatch.test.ts`:
- `savePending()` が引数なしで、各 item の `storeName` / `placeId` を**それぞれの**保存ペイロードに
  載せること（2件の item に別々の店を設定し、`createLog` が別々の `store` を受け取るのを検証）。
- `storeName` も `placeId` も空の item は、ペイロードに `store` キー自体が現れないこと
  （`buildDrinkLogPayload` の既存挙動）。
- `DrinkLogBatchItem` に `candidateSelection` が存在しないこと（型・初期値の回帰防止）。

`tests/pages/logsNew.test.ts`:
- 候補1件のとき `<select>` が描画されず、銘柄名入力が候補で埋まっていること。
- 候補2件以上のとき候補チップが2つ描画され、2つ目をクリックすると `brandText` がその候補になること。
- 候補0件のとき既存の注記が出ること。
- カードごとの店セレクト／店名入力が item の状態を更新すること。
- 「1杯目の店を全カードに適用」で2件目の item に1件目の店がコピーされること。
- 保存呼び出しに緯度経度が混入しないこと（前掲の必須テスト）。

---

## 受入条件
- `cd frontend && npm ci && npm run lint && npm run typecheck && npx vitest run && npm run generate` が全て成功。
  （**`npm test` は watch モードなので使わない。必ず `npx vitest run`**）
- `git diff` は `frontend/` と `.agent-tasks/` のみ。`lambda/` `infra/` に一切触れていない。
- 送信 JSON（`/api/drink-logs` の POST ボディ）の形が変わっていないこと。
- 座標が保存ペイロード・item 状態・localStorage のいずれにも入らないこと。
- 既存のスタイル踏襲（stone/amber Tailwind、日本語 UI 文言、`type="button"` の徹底）。

## 実装メモ
- 依存追加は不要。
- `items.indexOf(item)` を使っている既存の番号表示はそのままでよい。
- チップは `<button type="button">` で実装すること（`<label><input type="radio">` でも可だが、
  飲み方ピルと視覚を揃えること）。
