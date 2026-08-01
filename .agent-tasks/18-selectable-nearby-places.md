# Task 18: 近くの店候補リストを選択可能にする（Issue #29）

## 背景

Issue #29:

> 写真をアップロードしたとき、近くの店候補にリストで店名が表示されるが、表示されるだけで選択できるわけではない

`frontend/pages/logs/new.vue` の共有セクション「店を探す」にある「近くの店候補」リスト
（現状 254-261行付近）は `<div>` の読み取り専用リストで、クリックしても何も起きない。
一方、各カードには `<select id="place-{item.id}">` があり、そちらでは選択できる。
候補が並んでいるのにタップできないため、ユーザーは「選べない」と受け取る。

## スコープ

**`frontend/` のみ**。`lambda/` `infra/` は一切変更しない。API 契約・スキーマの変更も禁止。
主な変更対象:
- `frontend/pages/logs/new.vue`
- `frontend/composables/useDrinkLogBatch.ts`（ヘルパー追加のみ）
- `frontend/tests/pages/logsNew.test.ts` / `frontend/tests/composables/useDrinkLogBatch.test.ts`

---

## 変更1: 候補リストを選択可能なボタンにする

「近くの店候補」の各項目を `<div>` から `<button type="button">` に変え、**押すと
その店を未保存の全カードに適用する**（写真1枚のときは実質そのカードの選択になる）。

- ボタンの中身（店名・住所・`<GoogleAttributions>`）は現状の表示内容を維持する。
  `GoogleAttributions` がインタラクティブ要素を含む場合はボタンの外に出すこと
  （ボタン入れ子は不正な HTML になる）。実装前に
  `frontend/components/GoogleAttributions.vue` を確認して判断する。
- **選択状態を視覚とアクセシビリティの両方で示す**: `:aria-pressed` に加え、選択中は
  枠線・背景で区別できるスタイルを当てる（既存カードの選択チップ
  `role="group"` + `aria-pressed` の実装に倣うこと）。
- **選択判定**: 未保存カード（`saveStatus !== 'saved'`）が1枚以上あり、その**すべて**の
  `placeId` がその候補と一致するときに選択中とみなす。
- **再タップで選択解除**: 既に選択中の候補を押したら、未保存の全カードの `placeId` を空にする
  （トグル）。「店を選ばない」に相当する操作を候補リスト側でも可能にする。
- 保存済みカード（`saveStatus === 'saved'`）の `placeId` は**絶対に書き換えない**
  （既存 `copyStoreToPendingItems` と同じ不変条件）。

### 選択ロジックは composable の純関数として実装する

`frontend/composables/useDrinkLogBatch.ts` に、既存の `copyStoreToPendingItems` /
`clearPendingItemPlaceIds` と同じ流儀で純関数を追加し、`new.vue` からは import して使う
（テストが実装をコピーせず本物を叩けるようにするため — 既存テストの
`// Use the page's real helper rather than a copy` の意図を踏襲）。

```ts
/** True when every unsaved card already points at this place. */
export const isPlaceSelectedForPendingItems = (items: DrinkLogBatchItem[], placeId: string): boolean

/** Sets (or clears, when placeId is '') the place on every unsaved card. */
export const setPlaceOnPendingItems = (items: DrinkLogBatchItem[], placeId: string): void
```

- `isPlaceSelectedForPendingItems` は未保存カードが0枚のとき `false` を返すこと
  （空集合を「全一致」にすると、全部保存済みの画面で全候補が選択中に見える）。
- `placeId` が空文字のときの `isPlaceSelectedForPendingItems` の扱いはテストで固定すること。

## 変更2: 店名は自動入力しない（ポリシー厳守）

**Google の `display_name` は絶対にフォームへ入れない・保存しない。**
候補を押しても `storeName` は変更しない。永続化されるのは `place_id` とユーザーが自分で
入力した `storeName` のみ、という既存の設計を維持する。

候補リストの下に短い補足を置き、この挙動をユーザーに説明する。文言例:

> 店を選ぶと写真すべてに適用されます。記録に残す店名は各カードで入力してください。

（既存の 353行付近の説明文と重複した言い回しにならないよう調整してよい。）

## 変更3: 見出し・説明文の整合

- セクション説明「近くの店を検索して、写真ごとに店を選べます。」は、共有リストが
  全カード適用になることと矛盾しないよう調整する（例:「近くの店を検索して選ぶと全カードに
  適用されます。写真ごとの変更もできます。」）。
- 「最初の一杯の店を全カードに適用」ボタンは**残す**。こちらは `placeId` に加えて
  ユーザー入力の `storeName` もコピーする別機能であり、候補タップと役割が異なる。

---

## テスト

### `frontend/tests/composables/useDrinkLogBatch.test.ts`

- `setPlaceOnPendingItems` が未保存カードのみを更新し、`saveStatus === 'saved'` のカードを
  変更しないこと
- `setPlaceOnPendingItems(items, '')` が未保存カードの `placeId` を空にすること
- `isPlaceSelectedForPendingItems` が「未保存カード全一致で true」「一部不一致で false」
  「未保存カード0枚で false」を返すこと

### `frontend/tests/pages/logsNew.test.ts`

`renderLogPage` のテンプレート側スタブに新ヘルパーを配線した上で:

- **候補ボタンのクリックで未保存の全カードの `placeId` が更新されること**（`itemCount: 2`）
- **選択中の候補ボタンを再クリックすると `placeId` が空に戻ること**
- **選択中の候補ボタンが `aria-pressed="true"`、非選択が `"false"` になること**
- **保存済みカードの `placeId` が候補クリックで変わらないこと**
- **候補クリックで `storeName` が変化しないこと**（Google 表示名を入れない回帰防止）
- 既存の「per-card select で選べる」「最初の一杯の店を全カードに適用」テストが緑のままであること

---

## 受入条件

- `cd frontend && npm ci && npm run lint && npm run typecheck && npx vitest run && npm run generate` が全通過
  （**`npm test` は watch モードなので使わない**）
- `git diff` が `frontend/` と `.agent-tasks/` のみ。`lambda/` `infra/` に一切触れていない
- Google の `display_name` を `storeName` へ書き込むコードが存在しないこと（grep で確認）
- 保存済みカードを書き換える経路が存在しないこと
- 依存追加なし
