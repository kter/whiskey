# Task 04b: pending サインアップ username をメールに束縛する

## 問題（Medium）

`frontend/composables/useAuth.ts:71-77` の `pendingUsernameFor(email)` は sessionStorage の値を**入力メールとの一致検証なしに**返す。確認フォーム（signup.vue の「すでに確認コードをお持ちの方」経由）で別のメールを入力すると、以前のサインアップの username に対して confirmSignUp/resendSignUpCode が実行され、再送コードが**旧アドレスに届く**。

## 修正

- pending 情報を JSON `{ email: normalizedEmail, username }` として既存キー `whiskey.pending-signup-username` に保存。
- `pendingUsernameFor`: パースして `normalizeEmail(入力) === stored.email` の場合のみ保存済み username を使用。不一致・パース不能・レガシー素文字列は「無し」として扱い `deriveUsername(入力)` へフォールバック。

## 保持するもの

不透明 username 形式（`w<sha256hex>`）/ sessionStorage 消去後の再導出（既存テスト継続合格）/ 中立エラー文言 / 依存追加なし / frontend/ のみ。

## テスト追加

(a) 別メールでの確認は保存値でなくそのメールの導出 username を使う (b) resend も同様 (c) レガシー素文字列値の後方互換パース。

## 検証

`cd frontend && npm run lint && npm run typecheck && npx vitest run` 全緑。

## してはならないこと

上記以外のファイル変更・コミット作成。
