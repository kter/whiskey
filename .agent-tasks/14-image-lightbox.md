# Task 14: サムネイルクリックで画像を拡大表示（ライトボックス）

## 背景・スコープ
実機受入で「アップロード後、サムネイルをクリックしたときにポップアップで大きく表示してほしい」
との要望。**フロントエンドのみ**（`frontend/` 配下）で対応する。`lambda/`・`infra/`・スキーマ・
API 契約は一切変更禁止。`git diff` が frontend 以外に触れていたら不合格。

## 実装対象
1. **新規 `frontend/components/ImageLightbox.vue`** — 再利用可能な画像拡大モーダル。
2. **`frontend/pages/logs/new.vue`** — 確認カードのサムネイル（`item.previewUrl`）をクリックすると
   そのカードの画像をライトボックスで拡大表示。**これが主目的（アップロード後の確認画面）**。
3. **`frontend/pages/logs/[id].vue`** — 詳細ページの大画像をクリックで全画面ライトボックス表示
   （自然な補完。画像 URL は `log.image_url`。`@refreshed` で更新される値を使う）。

**タイムライン `pages/logs/index.vue` は変更しない** — サムネイルは既に詳細ページ（大表示）への
`NuxtLink` になっており、ライトボックスと競合するため現状維持。

## ImageLightbox.vue の仕様
既存の削除確認モーダル（`pages/logs/[id].vue` の `role="dialog"` ブロック）と同じ流儀に揃える。
**ブラウザネイティブの `<dialog>`/`alert`/`confirm` は使わない**（アプリ内モーダルのみ）。

- Props: `open: boolean`（`v-model:open` で開閉）, `src: string`, `alt: string`。
- 表示: 全画面オーバーレイ `fixed inset-0 z-30 flex items-center justify-center bg-black/80 p-4`、
  `role="dialog"` `aria-modal="true"` `:aria-label="alt"`。画像は
  `class="max-h-[90vh] max-w-[90vw] object-contain"`（縦横比維持・ビューポート内に収める）。
- 閉じる手段（すべて実装）:
  1. 右上の閉じるボタン（×、`aria-label="閉じる"`、`type="button"`）
  2. 背景（オーバーレイ）クリック — 画像自身のクリックでは閉じない（`@click.self`）
  3. Escape キー（`open` が true の間だけ `window` に keydown リスナ、`onBeforeUnmount` と
     閉じるタイミングで確実に解除）
- アクセシビリティ: 開いたときに閉じるボタンへフォーカスを移し、閉じたら元の要素へ戻す
  （`nextTick` + 直前の `document.activeElement` を保持）。
- スクロールロック: 開いている間は `document.body.style.overflow = 'hidden'`、閉じる/アンマウントで復元。
- 閉じる操作は `emit('update:open', false)` で行う（v-model 準拠）。

## 配線
### new.vue（確認カード）
現在:
```html
<img :src="item.previewUrl" :alt="`${items.indexOf(item) + 1}杯目の飲酒記録写真`"
     class="h-28 w-28 shrink-0 rounded-lg bg-stone-900 object-cover" />
```
- これを**クリック可能**にする: `<button type="button">` でラップ（または img に role/tabindex を付す
  のではなくボタン化を推奨）。`cursor-zoom-in` を付け、`aria-label="写真を拡大表示"`。
- クリックで、そのカードの `previewUrl` と alt をライトボックスに渡して開く。
- 複数カードがあるため、開いている画像の src/alt を単一の ref で管理し `ImageLightbox` を1つ配置。
- カードヘッダー側の小さいプレビュー（`h-16 w-16`, 180行付近）は対象外でよい（確認カードの
  `h-28 w-28` を主対象にする）。両方クリック可能にしても良いが、最低限 `h-28 w-28` を必須とする。

### [id].vue（詳細）
- `DrinkLogImage` が描画する大画像をクリックで開く。`DrinkLogImage` を**クリック可能な
  `<button type="button" class="block w-full cursor-zoom-in">` でラップ**し、クリックで
  `log.image_url`（存在時）をライトボックスに渡して開く。`image_url` が無い/プレースホルダ時は
  開かない（ボタンを `:disabled` にするか、ハンドラで早期 return）。
- 編集モード表示中は大画像も出ないので、通常表示時のみで良い。

## テスト（vitest, `frontend/tests/`）
- `ImageLightbox`（新規 `tests/components/imageLightbox.test.ts` 等）:
  - `open=true` で画像（正しい src/alt）とオーバーレイが描画される。`open=false` で描画されない。
  - 閉じるボタンクリック / 背景クリック / Escape キーで `update:open=false` が emit される。
  - 画像自身のクリックでは閉じない（`@click.self` の検証）。
- new.vue（既存 `tests/pages/logsNew.test.ts` に追加）:
  - 確認カードのサムネイルボタンをクリックするとライトボックスが開き、その項目の `previewUrl` が
    表示されること（happy-dom で描画確認）。既存テストは緑のまま。

## 受入条件
- `cd frontend && npm ci && npm run lint && npm run typecheck && npm run test -- --run && npm run generate` が全て成功。
- 確認カードのサムネイルをクリックで拡大モーダルが開き、×/背景/Escape で閉じる。詳細ページの大画像も
  クリックで全画面表示できる。タイムラインは従来通り詳細へ遷移（変更なし）。
- `git diff` は `frontend/` のみ。ネイティブ dialog/alert/confirm を使っていない。
- 既存コードのスタイル踏襲（stone/amber Tailwind、日本語 UI 文言、既存モーダルの `role="dialog"` 流儀）。

## 実装メモ
- 依存追加は不要（自前モーダルで実装。ライブラリは入れない）。
- `ImageLightbox` は `v-model:open` パターン。親（new.vue / [id].vue）は
  `const lightbox = reactive({ open: false, src: '', alt: '' })` のような単一状態で管理。
- Escape のグローバルリスナは開いている間だけ張り、閉じる/アンマウントで必ず解除（リーク防止）。
