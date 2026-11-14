# Issue の扱い（GitHub）

Issue と仕様は GitHub の `kter/whiskey` で管理する。操作には `gh` を使う。clone 内で実行すれば、
リポジトリは `git remote` から自動で決まる。

## よく使う操作

- 作成: `gh issue create --title "..." --body "..."`（複数行の本文はヒアドキュメントで渡す）
- 閲覧: `gh issue view <番号> --comments`
- 一覧: `gh issue list --state open --label ready-for-agent --json number,title,body,labels`
- コメント: `gh issue comment <番号> --body "..."`
- ラベル: `gh issue edit <番号> --add-label "..."` / `--remove-label "..."`
- クローズ: `gh issue close <番号> --comment "..."`

ラベルの意味は `docs/agents/triage-labels.md` を参照。

## PR の扱い

外部からの PR を機能要望として受け付ける運用はしていない。PR はトリアージの対象にしない。

Issue と PR は同じ番号空間を共有する。`#42` だけでは区別できないので、`gh pr view 42` で確かめ、
見つからなければ `gh issue view 42` を使う。

## スキルの指示との対応

- 「Issue トラッカーに登録する」と言われたら、GitHub に Issue を作る。
- 「関連チケットを取得する」と言われたら、`gh issue view <番号> --comments` を実行する。
