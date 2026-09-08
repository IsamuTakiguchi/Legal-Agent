#!/usr/bin/env bash
# Legal-Agent 起動（macOS / Linux）
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || exec bash ./install.sh
if curl -sf --max-time 2 http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
  python3 -c 'import webbrowser; webbrowser.open("http://127.0.0.1:8765/")' 2>/dev/null || open http://127.0.0.1:8765/ 2>/dev/null || true
  exit 0
fi
exec .venv/bin/python -m legal_agent serve
