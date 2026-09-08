# Legal-Agent

判例と文献を横断検索し、**出典付き**で回答するリーガルリサーチ AI エージェントです。
LegalBrain エージェント / Legalscape のような使い勝手を、**自分の PC 上で、自分の契約サービスと手持ちの書籍 PDF を使って**実現します。

| 種別 | ソース | 仕組み |
|---|---|---|
| 判例 | 裁判所 裁判例検索（courts.go.jp） | 公開サイトを直接検索し、判決全文 PDF を読む |
| 判例 | TKC ローライブラリー（lawlibrary.jp） | 自分のブラウザセッションで検索（要手動ログイン） |
| 文献 | 手持ちの書籍 PDF | ローカルに全文索引（SQLite FTS5）を作り、ページ単位で検索 |
| 文献 | LEGAL LIBRARY（legal-library.jp） | 自分のブラウザセッションで検索（要手動ログイン） |

回答は Claude（既定 `claude-opus-5`）がツールを使って調査し、本文中の `[1]` `[2]` が右側の出典パネル（判例の裁判所・日付・事件番号、書籍名・ページ、原典リンク）に対応します。

## セットアップ

```bash
git clone <this repo> && cd Legal-Agent
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
playwright install chromium                        # TKC / LEGAL LIBRARY を使う場合
cp .env.example .env                               # 編集して ANTHROPIC_API_KEY と PDF フォルダを設定
```

`.env` の主な項目:

- `ANTHROPIC_API_KEY` … Claude API キー
- `LEGAL_AGENT_PDF_DIRS` … 書籍 PDF のフォルダ（カンマ区切りで複数可）
- `LEGAL_AGENT_MODEL` / `LEGAL_AGENT_EFFORT` … 使用モデルと推論の深さ

## 使い方

```bash
python -m legal_agent index          # 書籍 PDF を索引化（差分更新。初回は冊数に応じて時間がかかる）
python -m legal_agent serve          # http://127.0.0.1:8765/ を開く
```

1. 画面上部のチェックボックスで使うソースを選びます。
2. TKC / LEGAL LIBRARY は「ログイン」ボタンを押すと専用ブラウザが開くので、そこで ID / パスワードを入力してログインします。
   Cookie はブラウザプロファイル（`data/browser_profile/`）に保存され、次回以降は不要です。**パスワードはアプリに保存しません。**
3. 質問を入力すると、エージェントが検索 → 本文確認 → 回答の順に進み、途中経過（どのソースを何件検索したか）が表示されます。
4. 「メモとして保存して」と頼むと `data/memos/` に Markdown で保存されます。

CLI から各ソースを単体で試すこともできます。

```bash
python -m legal_agent search-cases "整理解雇 四要件" --source courts
python -m legal_agent search-books "解雇権濫用" --source local
python -m legal_agent login tkc
```

## 重要な注意（利用規約・アクセス制御）

- TKC ローライブラリー・LEGAL LIBRARY の利用規約は、機械的アクセスや大量取得を禁じている可能性があります。
  本アプリは **利用者本人の操作の代行**（1 回の質問につき各ソース 3 回までの検索、6 件までの本文取得、人間並みの間隔）に限定し、
  一括クロールや本文の恒久保存は行いません。それでも、ご契約の条項に照らして問題がないかは **ご自身でご確認ください**。
- courts.go.jp（公開）にも 1 秒以上の間隔を空けてアクセスします。
- サーバは `127.0.0.1` にのみバインドされます。LAN 公開しないでください。

## TKC / LEGAL LIBRARY の画面構造の調整

両サービスは API がなく、ログイン後の画面構造は本リポジトリの開発環境からは確認できていません。
`legal_agent/sources/selectors.yaml` に **推定のセレクタ** を書いてあるので、初回はご自身の PC で次の手順で調整してください。

```bash
LEGAL_AGENT_DEBUG_DUMP=1 python -m legal_agent search-cases "解雇" --source tkc
```

- `data/debug/` に各ステップの HTML とスクリーンショットが保存されます。
- それを見て `selectors.yaml` の `search.input` / `search.row` / `detail.content` などを実際の要素に合わせます。
- LEGAL LIBRARY のビューアが画像描画で本文テキストを取れない場合、検索結果（書名・ページ・URL）までを返し、本文はブラウザで開いて確認する運用になります。

## 構成

```
legal_agent/
  app.py            FastAPI（/api/chat は SSE でストリーミング）
  static/index.html チャット UI + 出典パネル
  agent/            システムプロンプト、ツール、Claude tool_runner、引用解決、セッション保存
  sources/          courts.go.jp / TKC / LEGAL LIBRARY / ローカル PDF（selectors.yaml でサイト設定）
  browser/          Playwright 永続プロファイル管理、アクセス予算
  index/            PDF → SQLite FTS5（文字バイグラム）索引
  memo/             リサーチメモ出力
tests/              パーサ・索引・ツール・ランナー・API のテスト（`pytest`）
```

## 開発

```bash
pip install -e ".[dev]"
pytest
```

- `claude-opus-5` / Fable 系モデルではポリシー拒否時のサーバ側フォールバック（beta）を既定で有効にしています。
  不要なら `LEGAL_AGENT_FALLBACKS_ENABLED=false`。
- モデルの応答は adaptive thinking + `effort`（既定 high）で動きます。速さ優先なら `LEGAL_AGENT_EFFORT=medium`。
