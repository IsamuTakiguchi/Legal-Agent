# Legal-Agent

判例と文献を横断検索し、**出典付き**で回答するリーガルリサーチ AI エージェントです。
LegalBrain エージェント / Legalscape のような使い勝手を、**自分の PC 上で、自分の契約サービスと手持ちの書籍 PDF を使って**実現します。

| 種別 | ソース | 仕組み |
|---|---|---|
| 判例 | 裁判所 裁判例検索（courts.go.jp） | 公開サイトを直接検索し、判決全文 PDF を読む |
| 判例 | TKC ローライブラリー（lawlibrary.jp） | 自動ログインしたブラウザで検索 |
| 文献 | 手持ちの書籍 PDF | ローカルに全文索引（SQLite FTS5）を作り、ページ単位で検索 |
| 文献 | LEGAL LIBRARY（legal-library.jp） | 自動ログインしたブラウザで検索 |

回答は Claude（既定 `claude-opus-5`）がツールを使って調査し、本文中の `[1]` `[2]` が右側の出典パネル（判例の裁判所・日付・事件番号、書籍名・ページ、原典リンク）に対応します。

## 手動作業は 2 回だけ

```bash
pip install -e .            # ① インストール
python -m legal_agent       # ② 起動（初回は対話セットアップ → そのまま起動。ブラウザが自動で開く）
```

初回セットアップで聞かれるのは、Anthropic API キー・書籍 PDF のフォルダ・TKC と LEGAL LIBRARY のログイン ID/パスワードだけです。
あとは自動で行われます。

- Chromium の導入、書籍 PDF の索引化（起動時と 1 時間ごとに差分更新）
- TKC / LEGAL LIBRARY への自動ログイン（起動時に確認、セッション切れも自動で再ログイン）
- ログイン後の画面構造の解析（検索欄・結果一覧・本文のセレクタを Claude が発見し、実際に動くことを検証してから `data/selectors.override.yaml` に保存。以後はそれを使う）
- 検索が 0 件になるなど画面構造が変わった疑いがあるときは、自動で再解析（1 時間に 1 回まで）

ID/パスワードを保存したくない場合は空のままにしてください。その場合は画面上の「手動」ボタンでブラウザが開くので、そこでログインします（Cookie が残るので毎回は不要です）。

## 使い方

1. 画面上部のチェックボックスで使うソースを選びます。ソース名の横の点が緑ならログイン済み／利用可能です。
2. 質問を入力すると、エージェントが検索 → 本文確認 → 回答の順に進み、途中経過（どのソースを何件検索したか）が表示されます。
3. 「メモとして保存して」と頼むと `data/memos/` に Markdown で保存されます。
4. TKC / LEGAL LIBRARY の「自動設定」ボタンを押すと、その場で画面構造の解析をやり直せます。

CLI からも操作できます。

```bash
python -m legal_agent setup                      # 設定をやり直す
python -m legal_agent autoconf tkc               # セレクタ自動発見を手動で実行（ログを表示）
python -m legal_agent search-cases "整理解雇 四要件" --source courts
python -m legal_agent search-books "解雇権濫用" --source local
python -m legal_agent index --rebuild            # 索引を作り直す
python -m legal_agent login tkc                  # 表示ブラウザで手動ログイン
```

## 重要な注意（利用規約・アクセス制御）

- TKC ローライブラリー・LEGAL LIBRARY の利用規約は、機械的アクセスや大量取得を禁じている可能性があります。
  本アプリは **利用者本人の操作の代行**（1 回の質問につき各ソース 3 回までの検索、6 件までの本文取得、人間並みの間隔）に限定し、
  一括クロールや本文の恒久保存は行いません。それでも、ご契約の条項に照らして問題がないかは **ご自身でご確認ください**。
- ID/パスワードは `.env` に平文で保存されます（所有者のみ読める権限を付けます）。共有 PC では保存しないでください。
- courts.go.jp（公開）にも 1 秒以上の間隔を空けてアクセスします。
- サーバは `127.0.0.1` にのみバインドされます。LAN 公開しないでください。

## 自動設定がうまくいかないとき

両サービスは API がなく、ログイン後の画面構造は本リポジトリの開発環境からは確認できていません。
そのため初回は Claude が画面を解析して設定します（1〜3 分、API 利用料がかかります）。それでも動かない場合:

```bash
LEGAL_AGENT_DEBUG_DUMP=1 python -m legal_agent autoconf tkc
```

- `data/debug/` に各ステップの HTML とスクリーンショットが保存されます。
- 必要なら `data/selectors.override.yaml` を直接編集できます（`legal_agent/sources/selectors.yaml` と同じ構造。override が優先）。
- LEGAL LIBRARY のビューアが画像描画で本文テキストを取れない場合、検索結果（書名・ページ・URL）までを返し、本文はブラウザで開いて確認する運用になります。

## 構成

```
legal_agent/
  app.py            FastAPI（/api/chat は SSE でストリーミング。起動時に索引更新・自動ログイン）
  setup_wizard.py   初回セットアップ
  static/index.html チャット UI + 出典パネル
  agent/            システムプロンプト、ツール、Claude tool_runner、引用解決、セッション保存
  sources/          courts.go.jp / TKC / LEGAL LIBRARY / ローカル PDF（selectors.yaml でサイト設定）
  browser/          Playwright 永続プロファイル・自動ログイン、Claude によるセレクタ自動発見、アクセス予算
  index/            PDF → SQLite FTS5（文字バイグラム）索引
  memo/             リサーチメモ出力
tests/              パーサ・索引・ツール・ランナー・API・疑似サイトでのログイン/検索/自動設定のテスト（`pytest`）
```

## 開発

```bash
pip install -e ".[dev]"
pytest
```

- `claude-opus-5` / Fable 系モデルではポリシー拒否時のサーバ側フォールバック（beta）を既定で有効にしています。
  不要なら `LEGAL_AGENT_FALLBACKS_ENABLED=false`。
- モデルの応答は adaptive thinking + `effort`（既定 high）で動きます。速さ優先なら `LEGAL_AGENT_EFFORT=medium`。
