# Task 04d: Google 認証フラグの型強制バグ（Googleボタンが永久に出ない）

## 問題（dev 実機で検出）

`enableGoogleAuth: true` + `.env` に `NUXT_PUBLIC_GOOGLE_AUTH_ENABLED=1` を生成し、Cognito 側に Google IdP も登録済みなのに、`https://dev.whiskeybar.site/login` に Google ログインボタンが表示されない。

原因: **Nuxt の runtimeConfig は環境変数の値を型推論して上書きする**ため、`"1"` が **数値 `1`** になる。ビルド成果物 `frontend/.output/public/index.html` の埋め込みペイロードは `googleAuthEnabled:1`（クォートなし＝数値）。一方フロントの判定は厳密等価の文字列比較:

- `frontend/pages/login.vue:10` — `config.public.googleAuthEnabled === '1'`
- `frontend/pages/signup.vue:13` — 同上
- `frontend/composables/useAuth.ts:302` — `!== '1'` で例外送出

このため常に無効判定になり、フラグを有効にしても Google ログインが利用できない。

## 修正

- 判定を1か所の共通ヘルパー（例: `frontend/composables/useAuth.ts` から export、または `frontend/utils/` の小関数）に集約し、**文字列・数値の両方を受理しつつ fail-closed を維持**する。受理する真値は `'1'` / `1` / `'true'` / `true` のみ。それ以外（`undefined`・`'0'`・`0`・空文字・任意文字列）はすべて無効。
  - `Boolean(value)` のような緩い判定は禁止（`'0'` が true になり fail-closed が壊れる）。
- 上記3箇所すべてを共通ヘルパー経由に置換（直接比較を残さない — grep で確認できること）。
- `frontend/nuxt.config.ts:33` の `googleAuthEnabled` は現状のままでよいが、型強制が起きる旨のコメントを1行添える。

## テスト（vitest）

- ヘルパーの真値表: `'1'` / `1` / `'true'` / `true` → 有効、`'0'` / `0` / `undefined` / `''` / `'yes'` / `null` → 無効。
- login ページ: フラグが数値 `1` のとき Google ボタンが描画される（現行バグの回帰テスト）／`0` のとき描画されない。
- `useAuth` の Google サインイン: 無効時に例外、有効時（数値1含む）は Amplify の signInWithRedirect が呼ばれる（既存モック方針に合わせる）。

## 検証

`cd frontend && npm run lint && npm run typecheck && npx vitest run` 全緑。

## してはならないこと

バックエンド・infra・deploy.sh の変更、認証ロジックそのものの変更（プロバイダ名や redirect 契約は現状維持）、上記以外のファイル変更、コミット作成。
