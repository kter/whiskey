# クラウドのエージェントとの分担

Claude Code on the web と Codex Cloud に作業を渡すときの流れ。環境の準備と各クラウドの癖は AGENTS.md の「クラウドのエージェントで作業するとき」を参照。

## 流れ

1. **Issue を作る。** `.github/ISSUE_TEMPLATE/agent-task.md` の形で、やること・範囲・受け入れ条件を書く。迷いそうな判断は先に決めて書いておく。依存の追加など人の承認が要るものは「人の承認が要るもの」に書く。
2. **`ready-for-agent` を付ける。** AWS の実機、認証情報、dev・prd での確認が要るものは `ready-for-human` にする。
3. **どちらかのクラウドに渡す。** プロンプトには Issue 番号、PR のベース、AGENTS.md に従うこと、AWS に触らないことを書く。並行で別の作業が走っているなら、触ってはいけないファイルも書く。
4. **PR をレビューする。** レビューする側は、実装したエージェントの自己申告ではなく、差分・CI・PR の説明にある実行結果を見る。振る舞いが変わりうる箇所は差分を読んで確かめる。問題があれば PR にコメントし、同じエージェントに差し戻す。
5. **マージは人が決める。** CI の `Test / Lint / Build` が成功していることを確かめてから。
6. **dev での実機確認とデプロイは人（または手元の Claude）が行う。** クラウドからは届かない。

## どちらに渡すか

決まりはない。目安として:

- **Claude Code on the web**: Docker デーモンが無い・ブラウザまわりなど、制約が厳しい側で先に通したいとき。SessionStart フックで依存が自動で入る
- **Codex Cloud**: Docker が要るとき、実装量が多いとき。環境 `whiskey` の install script が Python 3.11 / Node 22 を入れる

## 承認で止まる操作

- Claude Code on the web では、`.mcp.json` のような機密扱いのファイルの編集で権限確認が出て止まる。承認する人がいる時間に渡すか、Issue に書いておく。
- エージェント（手元の Claude を含む）は、別のエージェントへの権限付与やマージを代行しない。

## 実績

| Issue | 担当 | PR | メモ |
| --- | --- | --- | --- |
| #73 Makefile の環境変数名 | Claude Code on the web | #75 | |
| #74 バージョン固定と `make check` | Codex Cloud | #76 | `unexport AWS_PROFILE` が外れていたのを差し戻し |
| #78 moto への置き換え | Codex Cloud | #80 | moto が presigned POST のポリシーを検証しない差を文書化 |
| #79 ruff と `.mcp.json` | Claude Code on the web | #81 | `.mcp.json` の編集で人の承認待ちになった |
