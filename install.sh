#!/usr/bin/env bash
# Legal-Agent 導入スクリプト（macOS / Linux）。`bash install.sh` またはダブルクリック（macOS は install.command にコピー可）。
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Legal-Agent 導入 ==="
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then
    echo "Python 3.11 以上が見つかりません。Homebrew でインストールします..."
    brew install python@3.12 && PY="$(brew --prefix)/bin/python3.12"
  else
    echo "Python 3.11 以上が見つかりません。https://www.python.org/downloads/ からインストールして再実行してください。"
    exit 1
  fi
fi
echo "Python: $PY"

[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
.venv/bin/python -m pip install --disable-pip-version-check -q -e .
chmod +x start.sh
echo "導入が完了しました。起動します（ブラウザが開きます。初回は画面で API キーと書籍フォルダを設定してください）。"
exec ./start.sh
