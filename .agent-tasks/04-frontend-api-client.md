# Task 04: フロントエンド共通 API クライアント・IDトークン切替・認証UI・契約追従

## Goal

フロントエンドを新バックエンド契約（ID トークン / whiskey_id / next_token / 公開パス分離）へ追従させ、共通 API クライアントへ集約し、Email/Password 認証 UI と各種修正を実装する。**対象は frontend/ のみ**。

## 背景（必読）

- タスク01〜03適用済み前提。バックエンドは: オーソライザーは **ID トークン**検証 / レビューは `whiskey_id` 必須・`image_url` 廃止・`is_public` トグル・単一 `serving_style`（大文字enum）/ 一覧系は `limit`+`next_token` / 公開一覧は `/api/reviews/public` / パスは**末尾スラッシュなし**。
- ローカル開発（タスク05）が `import.meta.dev && NUXT_PUBLIC_MOCK_AUTH=1` のモック認証を使う予定 — その受け皿となる認証状態の抽象化もここで整える。

## 変更対象

- `frontend/composables/`（useApi.ts 新規、useAuth/useWhiskeys/useWhiskeySearch/useSuggestWhiskeys 改修）
- `frontend/pages/**`（login/signup/reviews 系/index/ranking/search、直接 fetch の除去）
- `frontend/components/WhiskeySearchInput.vue` / `frontend/layouts/default.vue` / `frontend/plugins/amplify.client.ts` / `frontend/types/whiskey.ts`
- `frontend/package.json`（lint/typecheck スクリプト + ESLint flat config + vue-tsc devDependency）
- `frontend/tests/**`

## 要求仕様

### 1. `useApi()` 共通クライアント
- baseURL 正規化（末尾スラッシュ除去 — execute-api 形式 `.../dev/` とカスタムドメイン両対応）+ リクエストパスも末尾スラッシュなしに統一。
- **認証モード宣言 `none | optional | required`**: none はトークン取得せず、optional は取得失敗を握って匿名続行、required は失敗時ログイン誘導（公開APIで getToken 例外落ちする現行問題の解消）。
- エラー正規化（JSON エラーボディ / 429・503 のユーザー向けメッセージ化）。
- 全 composable と**ページ内の直接 fetch**（`pages/index.vue` / `reviews/[id].vue` / `reviews/[id]/edit.vue` 等）を useApi 経由に移行。受入: composable 外の直接 fetch ゼロ（grep）。

### 2. 認証（useAuth / amplify.client.ts）
- `getToken()` を **idToken** 返却に変更。
- **`currentUserId` の単一契約**を公開（`AuthUser.userId` / 属性 sub から導出）— `reviews/index.vue:51` の `user.value.sub` 参照を置換。
- **Google ログイン修正**: `provider: {custom:'Google'}` → `provider: 'Google'`。`amplify.client.ts` の redirect_uri エラーを握り潰すグローバルハンドラを削除。
- **正規サインアウト**: Amplify `signOut` + `redirectSignOut` を実装（現行のローカルストレージ消去だけの偽サインアウトを置換）。サインアウト失敗時の全ストレージ消去は Amplify/Cognito 関連キーのみに限定。
- **Cognito ドメインのハードコード除去**: `NUXT_PUBLIC_COGNITO_DOMAIN`（裸ホスト名）から構成。www 付き redirect URI を削除。
- `layouts/default.vue` の追跡されない5秒ポーリングを廃止（または unmount で clearInterval）。
- **auth-ready 契約**: 認証初期化完了を Promise/state で共有し、ページは初期化完了後にデータ取得（ハードリロードでレビュー一覧が空になる競合の解消）。
- **ローカルモック認証の受け皿**: `import.meta.dev && useRuntimeConfig().public.mockAuth === '1'` のときのみ有効なローカル認証プロバイダ（ダミーユーザー + isAuthenticated=true + getToken はダミー値）。**非 dev ビルドで NUXT_PUBLIC_MOCK_AUTH が設定されていたらビルド失敗**（nuxt.config で検査）。

### 3. Email/Password 認証 UI
- login.vue / signup.vue（現行 Google 専用）に email サインイン・登録・確認コード・再送 UI を追加。
- **Google ボタンは `NUXT_PUBLIC_GOOGLE_AUTH_ENABLED === '1'` のときのみ表示**（fail-closed: 未定義は非表示）。
- **サインアップの username**: 正規化 email + 公開アプリ定数ソルトの sha256 から決定的に導出した不透明 username（英数字。email/UUID 形式でない）。email は属性として登録。**未確認 username は sessionStorage 保持 + email から再導出可能**（タブを閉じても確認/再送を継続できる）。sessionStorage 消去後の確認継続テスト付き。
- エラーメッセージはユーザー存在の有無を区別しない文言。

### 4. レビュー UI の契約追従
- `WhiskeySearchInput.vue`: 選択イベントに `id` を含める。placeholder 等の「蒸留所」文言を名前検索専用に修正。
- 作成フォーム: **候補選択必須**（選択が無ければ送信不可 + 案内。テキスト編集で id 失効）。`is_public` トグル追加。**飲み方は単一選択**に変更（現行は複数選択で先頭だけ送る偽装）。ペイロードは `whiskey_id` + 大文字 enum。
- 編集フォーム: 銘柄は読み取り専用（変更はレビュー削除→再作成の案内）。
- 一覧: `page/per_page`・`count` 前提を `limit`/`next_token` + 「さらに読み込む」に置換（レビュー/検索/list 共通）。公開一覧の呼び出しを `/api/reviews/public` へ。
- `image_url` の表示/送信コードを削除。

### 5. 品質ゲート
- リポジトリ全域の `console.log` デバッグ出力を除去（auth/callback.vue の OAuth URL ログ含む）。console.error は文脈があるものだけ残してよい。
- ESLint flat config（Nuxt 3 向け）新設 + `lint` 修正。`typecheck` スクリプト（`nuxi typecheck`）+ 対応版 `vue-tsc` を devDependencies に固定。既存コードの型エラーも修正（useAuth の UserProfile 不整合等）。
- vitest: useApi / useAuth（モック認証・トークン）/ ページネーションの新規テスト + 既存テスト更新。

## 受入条件

1. `npm ci && npm run lint && npm run typecheck && npx vitest run && npm run generate` すべて成功（クリーン環境）
2. grep: composable 外の直接 fetch ゼロ / `console.log` 残存ゼロ / accessToken 参照ゼロ
3. lambda/ と infra/ は未変更

## してはならないこと

- バックエンド・infra の変更、実 AWS アクセス、コミット作成
- UI デザインの大規模刷新（既存 Tailwind トーンを維持。デザインパスは Phase 5）
