# Task 03c: reserved concurrency の環境設定化（dev デプロイ失敗の修正）

## 問題（実デプロイで検出）

`WhiskeyApp-Dev` のデプロイが `RankingAggregatorFunction` の `ReservedConcurrentExecutions=1` で失敗:
"Specified ReservedConcurrentExecutions ... decreases account's UnreservedConcurrentExecution below its minimum value of [10]"

dev アカウントの Lambda 同時実行クォータが既定最小値 10 のままで、reserved を1でも設定すると未予約分が下限 10 を割る。Phase 4 で追加予定の analyze(rc=2)/places(rc=3) も同じ問題を踏む。

## 修正

- `infra/config/environments.ts` に `lambdaReservedConcurrency?: { aggregator?: number; analyze?: number; places?: number }` を追加。**dev は未設定（= reserved なし）**、prd 用の推奨値はコメントで記載（アカウントクォータ引き上げ後に設定する旨も）。
- `infra/lib/whiskey-infra-stack.ts`: aggregator の `reservedConcurrentExecutions` を設定値がある場合のみ付与。
- 濫用防御の代替は既存の AppState カウンタ + メソッドスロットリングが担う旨をコード/README コメントに1行（reserved はクォータ引き上げ後の追加防御という位置づけ）。
- jest: dev テンプレートに ReservedConcurrentExecutions が**存在しない**こと、設定値を与えた場合に付与されることをテスト。

## 検証

`cd infra && npx tsc --noEmit && npx jest && npx cdk synth -c env=dev > /dev/null` 全緑。

## してはならないこと

Lambda コード変更・他プロパティ変更・コミット作成。
