# トリアージ用ラベル

スキルが使う5つの役割と、GitHub 上の実際のラベル名の対応。現在はすべて同じ名前を使っている。

| 役割 | GitHub のラベル | 意味 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | メンテナの評価待ち |
| `needs-info` | `needs-info` | 報告者からの追加情報待ち |
| `ready-for-agent` | `ready-for-agent` | 仕様と受け入れ条件が固まり、エージェントに渡せる |
| `ready-for-human` | `ready-for-human` | 人間が実装する必要がある（AWS 実機、認証情報、判断が要るものなど） |
| `wontfix` | `wontfix` | 対応しない |

クラウドのエージェント（Claude Code on the web、Codex Cloud）に渡す Issue には `ready-for-agent` を付ける。
AWS の認証情報や dev・prd 環境での実機確認が要る作業は `ready-for-human` にする。
