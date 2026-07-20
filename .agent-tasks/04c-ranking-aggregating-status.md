# Task 04c: ランキングの aggregating 応答をフロントで処理する

## 問題（実機スモークで検出）

`GET /api/whiskeys/ranking` は集計キャッシュが fail-closed のとき `{"status": "aggregating"}` を返す（正常設計）。フロントの `useWhiskeys` ランキング取得はこの形状を想定しておらず、「data.rankings is not iterable」のエラーバナーが出る（「集計中です」表示自体は出るが、エラーも併発する）。

## 修正

- `frontend/composables/useWhiskeys.ts` のランキング処理: 応答が `{status: 'aggregating'}` の場合はエラーにせず「集計中」状態として返す（既存の集計中表示のみが出る挙動へ）。素の配列形状（レガシー）と `{rankings, pagination}` 形状の両方も防御的に受理。
- `frontend/pages/ranking.vue`: aggregating 状態でエラーバナーを出さない。
- `docs/LOCAL_DEV.md` のトラブルシューティングに追記: ランキングが「集計中」のままの場合は `make local-aggregate` を実行（ローカルには15分スケジューラが無い）。
- vitest: aggregating 応答・配列形状・paginated 形状の3ケースのテスト追加。

## 検証

`cd frontend && npm run lint && npm run typecheck && npx vitest run` 全緑。

## してはならないこと

バックエンド・infra の変更、上記以外のファイル変更、コミット作成。
