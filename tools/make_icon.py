"""legal_agent/static/legal-agent.ico を作り直す（ロゴを変えたときだけ実行する）。

図案は legal_agent/static/index.html の <symbol id="logo">（天秤＋きらめき）と同じもので、
デスクトップの壁紙が明るくても暗くても見えるようニアブラックの角丸タイルに白で載せる。

Pillow も cairosvg も入っていないため、Chromium（Playwright）で各サイズを描いて
canvas から生の RGBA を取り出し、ICO を直接組み立てる。
  - 16〜64px: BMP(DIB) エントリ（古い表示経路でも確実に出る）
  - 128/256px: PNG エントリ（サイズを抑える）

使い方: python tools/make_icon.py [出力先.ico]
"""
from __future__ import annotations

import asyncio
import base64
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "legal_agent" / "static" / "legal-agent.ico"
CHROMIUM = "/opt/pw-browsers/chromium"

# index.html の <symbol id="logo"> と同じ図案
MARK = (
    '<rect x="12.6" y="5" width="2.8" height="18"/>'
    '<rect x="3" y="8.6" width="22" height="2.9" rx="1.45"/>'
    '<rect x="6.5" y="23" width="15" height="2.9" rx="1.45"/>'
    '<path d="M1.4,14.2 A4.6,4.6 0 0 0 10.6,14.2 Z"/>'
    '<path d="M17.4,14.2 A4.6,4.6 0 0 0 26.6,14.2 Z"/>'
    '<path d="M27.8,0.2 Q28.5,3.5 31.8,4.2 Q28.5,4.9 27.8,8.2 Q27.1,4.9 23.8,4.2 Q27.1,3.5 27.8,0.2 Z"/>'
)
TILE = "#111111"
# (サイズ, マークの拡大率, タイルの角丸率) — 小さいサイズは余白を詰めて潰れを防ぐ
SIZES = [(16, 0.86, 0.20), (20, 0.84, 0.21), (24, 0.82, 0.21), (32, 0.78, 0.22),
         (40, 0.76, 0.22), (48, 0.74, 0.22), (64, 0.72, 0.22), (128, 0.72, 0.22), (256, 0.72, 0.22)]
PNG_FROM = 128  # このサイズ以上は PNG エントリにする

# マークの実際の描画範囲（32 単位系）。タイル中央に収めるために使う
BBOX = (1.4, 0.2, 31.8, 26.0)


def svg_for(size: int, scale: float, radius: float) -> str:
    """1 辺 size px のタイル入りアイコンの SVG。"""
    bw, bh = BBOX[2] - BBOX[0], BBOX[3] - BBOX[1]
    box = 32 * scale                      # マークを収める正方形の一辺（32 単位系）
    s = min(box / bw, box / bh)           # マークの拡大率
    tx = (32 - bw * s) / 2 - BBOX[0] * s  # 中央寄せ
    ty = (32 - bh * s) / 2 - BBOX[1] * s
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 32 32">'
        f'<rect width="32" height="32" rx="{32 * radius:.2f}" fill="{TILE}"/>'
        f'<g fill="#ffffff" transform="translate({tx:.3f} {ty:.3f}) scale({s:.4f})">{MARK}</g></svg>'
    )


async def render() -> list[tuple[int, bytes, bytes]]:
    """各サイズについて (size, RGBA, PNG) を返す。"""
    from playwright.async_api import async_playwright

    out = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROMIUM)
        page = await browser.new_page()
        await page.goto("about:blank")
        for size, scale, radius in SIZES:
            rgba_b64, png_b64 = await page.evaluate(
                """async ({svg, size}) => {
                    const img = new Image();
                    img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)));
                    await img.decode();
                    const c = document.createElement('canvas');
                    c.width = c.height = size;
                    const ctx = c.getContext('2d');
                    ctx.drawImage(img, 0, 0, size, size);
                    const d = ctx.getImageData(0, 0, size, size).data;
                    let s = '';
                    for (let i = 0; i < d.length; i++) s += String.fromCharCode(d[i]);
                    return [btoa(s), c.toDataURL('image/png').split(',')[1]];
                }""",
                {"svg": svg_for(size, scale, radius), "size": size},
            )
            out.append((size, base64.b64decode(rgba_b64), base64.b64decode(png_b64)))
        await browser.close()
    return out


def bmp_entry(size: int, rgba: bytes) -> bytes:
    """ICO 用の BITMAPINFOHEADER + 下から上の BGRA + AND マスク。"""
    rows = []
    for y in range(size - 1, -1, -1):  # BMP は下から上
        row = bytearray()
        for x in range(size):
            i = (y * size + x) * 4
            r, g, b, a = rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    xor = b"".join(rows)
    mask_row = (size + 31) // 32 * 4  # 1bpp・4 バイト境界
    and_mask = b"\x00" * (mask_row * size)
    header = struct.pack(
        "<IiiHHIIiiII",
        40, size, size * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0,
    )
    return header + xor + and_mask


def build_ico(images: list[tuple[int, bytes, bytes]]) -> bytes:
    entries, blobs, offset = [], [], 6 + 16 * len(images)
    for size, rgba, png in images:
        data = png if size >= PNG_FROM else bmp_entry(size, rgba)
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        blobs.append(data)
        offset += len(data)
    return struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(blobs)


def main() -> None:
    images = asyncio.run(render())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build_ico(images))
    print(f"{OUT} ({OUT.stat().st_size:,} バイト / {len(images)} サイズ: "
          + ", ".join(str(s) for s, _, _ in images) + ")")


if __name__ == "__main__":
    main()
