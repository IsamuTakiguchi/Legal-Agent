# Legal-Agent

判例と文献を横断検索し、**出典付き**で回答するリーガルリサーチ AI エージェントです。
LegalBrain エージェント / Legalscape のような使い勝手を、**自分の PC 上で、自分の契約サービスと手持ちの書籍 PDF を使って**実現します。

| 種別 | ソース | 仕組み |
|---|---|---|
| 判例 | 裁判所 裁判例検索（courts.go.jp） | 公開サイトを直接検索し、判決全文 PDF を読む |
| 文献 | 手持ちの書籍 PDF | ローカルに全文索引（SQLite FTS5）を作り、ページ単位で検索 |
| 判例 | TKC ローライブラリー（lawlibrary.jp） | **保留中**。アプリからはアクセスせず、手動検索用リンクを案内するだけ |
| 文献 | LEGAL LIBRARY（legal-library.jp） | **保留中**。同上 |

回答は Claude（既定 `claude-opus-5`）がツールを使って調査し、本文中の `[1]` `[2]` が右側の出典パネル（判例の裁判所・日付・事件番号、書籍名・ページ、原典リンク）に対応します。

## 導入は 3 手順（Windows）

1. このリポジトリを ZIP でダウンロードして展開する（または `git clone`）。
2. 展開したフォルダの **`install.bat` をダブルクリック**する。Python が無ければ自動でインストールし、アプリを導入し、デスクトップに「Legal-Agent」ショートカットを作って起動します（数分）。
3. 自動で開いたブラウザの画面で、**Anthropic API キーを貼り付け、書籍 PDF のフォルダにチェック**を入れて「保存して開始」を押す。

以後は、デスクトップの「Legal-Agent」ショートカットをダブルクリックするだけです（ブラウザが自動で開きます。既に起動していればブラウザだけ開きます）。

- API キーは [Anthropic コンソール](https://console.anthropic.com/settings/keys) で「Create Key」を押して発行します（これだけは自動化できません）。キーはこの PC の `.env` にのみ保存されます。
- 書籍 PDF のフォルダは、PC に同期されている OneDrive の中から PDF のあるフォルダを件数付きで一覧するので、チェックするだけです。
- 索引化は保存直後にバックグラウンドで始まり、以後は起動時と 1 時間ごとに差分更新されます。
- macOS / Linux は `bash install.sh`（以後は `./start.sh`）。ターミナルで設定したい場合は `python -m legal_agent setup`。
- Windows のログオン時に自動起動したい場合: `Win + R` → `shell:startup` で開くフォルダに、デスクトップの「Legal-Agent」ショートカットをコピーします。

### うまく動かないとき

- `install.bat` で Python のインストールに失敗する（winget が無い等）: 開いた python.org のページからインストーラーを実行し、「Add python.exe to PATH」にチェックを入れてから `install.bat` をもう一度ダブルクリック。
- 「ポートが使用中」: 既に起動しています。ブラウザで http://127.0.0.1:8765/ を開くか、`.env` に `LEGAL_AGENT_PORT=8766` を追加。
- 画面が開かない: `start.bat` の黒いウィンドウを閉じていないか確認し、http://127.0.0.1:8765/ を直接開く。

### OneDrive 上の書籍 PDF について

- 前提: アプリを動かす PC に OneDrive 同期クライアントが入っていること（Windows なら標準。`C:\Users\<名前>\OneDrive` などに同期フォルダがある状態）。Microsoft Graph API や Azure のアプリ登録は使いません。
- セットアップ画面は環境変数 `OneDriveConsumer` / `OneDrive` などから同期フォルダを検出し、PDF を含むフォルダを件数付きで一覧します。別の場所ならパスを貼り付けられます。
- Windows の「ファイル オンデマンド」でクラウドのみになっている PDF は、索引時に順次ダウンロードされます（冊数が多いと初回は時間がかかります）。確実にしたい場合は、エクスプローラーでフォルダを右クリック →「このデバイス上で常に保持する」を選んでください。
- ダウンロードできなかったファイル（オフライン、同期中のロックなど）は失敗として記録され、次回の自動スキャン（1 時間ごと、または画面の「索引を更新」）で再試行されます。
- 画面左の「書籍索引」に、フォルダが見つからない場合（OneDrive 未サインインなど）や未ダウンロードの冊数が表示されます。

## 使い方

1. 画面上部のチェックボックスで使うソースを選びます。ソース名の横の点が緑なら利用可能です（保留中のソースは灰色）。
2. 質問を入力すると、エージェントが検索 → 本文確認 → 回答の順に進み、途中経過（どのソースを何件検索したか）が表示されます。
3. 「メモとして保存して」と頼むと `data/memos/` に Markdown で保存されます。

CLI からも操作できます。

```bash
python -m legal_agent setup                      # ターミナルで設定をやり直す（通常は画面から）
python -m legal_agent search-cases "整理解雇 四要件" --source courts
python -m legal_agent search-books "解雇権濫用" --source local
python -m legal_agent index --rebuild            # 索引を作り直す
```

## 契約サービス（TKC / LEGAL LIBRARY）は保留中

両サービスの利用規約原文を確認した結果を踏まえ、現在は **どちらも保留** にしています。アプリはこれらのサイトに一切アクセスせず、エージェントが必要と判断したときに「利用者が自分で検索するためのリンク」を案内するだけです。
詳細と条文の引用は [docs/TERMS_REVIEW.md](docs/TERMS_REVIEW.md) を参照してください。

| サービス | 確認結果 |
|---|---|
| LEGAL LIBRARY | 第 8 条で「自動化された手段によるアクセス」「AI 等の使用」を明文で禁止。**許容されない可能性が高い** |
| TKC ローライブラリー | 自動化手段・AI 利用の明文禁止はなし。ただし判例本文を Claude API に送る点（9-1 目的外利用の「複製」との関係）と、LEX/DB 等の個別規約が未確認 |

各社への照会文の例も同文書にあります。許諾や確認が得られたら `.env` に次を追加して `python -m legal_agent setup` をやり直すと、自動ログイン（ID/パスワードを `.env` に保存）と、ログイン後の画面構造の自動解析（検索欄・結果一覧・本文のセレクタを Claude が発見して検証し `data/selectors.override.yaml` に保存）が有効になります。

```
LEGAL_AGENT_TKC_ENABLED=true
LEGAL_AGENT_LEGAL_LIBRARY_ENABLED=true
```

その他の注意:

- 本アプリは **利用者本人の操作の代行** に限定し、一括クロールや本文の恒久保存は行いません。有効化後も 1 質問あたり検索 3 回・本文 6 件・1 秒以上の間隔に制限されます。
- ID/パスワードは `.env` に平文で保存されます（所有者のみ読める権限を付けます）。共有 PC では保存しないでください。
- courts.go.jp（公開）にも 1 秒以上の間隔を空けてアクセスします。
- サーバは `127.0.0.1` にのみバインドされます。LAN 公開しないでください。

## （有効化後）自動設定がうまくいかないとき

両サービスは API がなく、ログイン後の画面構造は本リポジトリの開発環境からは確認できていません。
そのため初回は Claude が画面を解析して設定します（1〜3 分、API 利用料がかかります）。UI の「自動設定」ボタンか次のコマンドでやり直せます。それでも動かない場合:

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
  setup_wizard.py   セットアップ処理（ブラウザ版 /api/setup とターミナル版で共用）
install.bat / start.bat   Windows 用の導入・起動（install.sh / start.sh は macOS・Linux 用）
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
