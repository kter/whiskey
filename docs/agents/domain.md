# ドメイン文書の読み方

コードを調べる前に、リポジトリ直下の `CONTEXT.md` を読む。Drink Log、Recording Session、
Analysis Result、Whiskey Candidate、Usage Budget、Completion などの用語と、その定義がある。

## 用語を揃える

- コードの命名、PR の説明、Issue の本文では `CONTEXT.md` の用語を使う。
  `CONTEXT.md` が避けるとしている言い換えは使わない。
- 必要な概念が `CONTEXT.md` に無いときは、勝手に新語を作らず、PR か Issue で用語の追加を提案する。

## 設計判断の記録

ADR のディレクトリ（`docs/adr/`）はまだ無い。過去の設計判断は、次の場所に残っている。

- `AGENTS.md`（アーキテクチャ、モデル選定の経緯、デプロイの作法）
- `docs/` 配下の仕様書（例: `docs/DRINK_LOG_AI_API.md`、`docs/LLM_QUALITY.md`）
- 該当する PR の説明とレビューのやり取り（`gh pr view <番号> --comments`）

自分の変更がこれらの判断と食い違う場合は、黙って上書きせず、PR の説明に食い違いを明記する。
