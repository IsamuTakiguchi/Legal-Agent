#!/usr/bin/env bash
# Windows 用インストーラ Legal-Agent-Setup.exe を作る。
#
# NSIS は Linux でも Windows 用の .exe を作れるので、CI（.github/workflows/installer.yml）でも
# 手元でも同じ手順で動く。必要なもの: makensis（apt install nsis）。
#
#   使い方: tools/build_installer.sh [出力先ディレクトリ]   既定は dist/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dist}"
PAYLOAD="$OUT_DIR/payload"
OUTFILE="$OUT_DIR/Legal-Agent-Setup.exe"

cd "$ROOT"

# バージョン: コミット数から単調増加の 4 桁を作る（NSIS の VIProductVersion は 4 桁必須）。
# 表示用には短い SHA も添える。
COUNT="$(git rev-list --count HEAD 2>/dev/null || echo 0)"
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
VERSION="0.1.${COUNT}.0"
DISPLAY_VERSION="0.1.${COUNT} (${SHA})"

# 同梱するのは実行に必要なファイルだけ。tests/ docs/ tools/ .github/ は入れない
# （tests/fixtures だけでリポジトリの半分を占めるため）。
rm -rf "$PAYLOAD"
mkdir -p "$PAYLOAD"
FILES="$(git ls-files | grep -vE '^(tests|docs|tools|packaging|\.github)/')"
echo "$FILES" | while IFS= read -r f; do
  [ -n "$f" ] || continue
  mkdir -p "$PAYLOAD/$(dirname "$f")"
  cp -p "$f" "$PAYLOAD/$f"
done

COUNT_FILES="$(echo "$FILES" | grep -c . || true)"
echo "同梱: ${COUNT_FILES} ファイル / $(du -sh "$PAYLOAD" | cut -f1)"
echo "バージョン: ${VERSION}  (${DISPLAY_VERSION})"

makensis -V2 \
  "-DVERSION=$VERSION" \
  "-DDISPLAY_VERSION=$DISPLAY_VERSION" \
  "-DPAYLOAD=$PAYLOAD" \
  "-DOUTFILE=$OUTFILE" \
  "$ROOT/packaging/legal-agent.nsi"

# CI がタグ名に使えるよう、バージョンを書き出しておく（唯一の出どころ）
printf '%s' "0.1.${COUNT}" > "$OUT_DIR/VERSION"

echo "できました: $OUTFILE ($(du -h "$OUTFILE" | cut -f1))"
