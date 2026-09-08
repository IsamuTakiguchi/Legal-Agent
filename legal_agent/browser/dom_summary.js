// ページ構造の要約（Claude によるセレクタ自動発見用）。page.evaluate で実行する。
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const cls = (el) => Array.from(el.classList || []).filter(c => /^[A-Za-z_][\w-]*$/.test(c) && c.length < 40).slice(0, 3);
  const piece = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id && /^[A-Za-z_][\w-]*$/.test(el.id)) return s + '#' + el.id;
    const c = cls(el); if (c.length) s += '.' + c.join('.');
    return s;
  };
  const cssPath = (el) => {
    const parts = []; let cur = el; let depth = 0;
    while (cur && cur.nodeType === 1 && depth < 4) {
      const p = piece(cur); parts.unshift(p);
      if (p.includes('#')) break;
      cur = cur.parentElement; depth++;
    }
    return parts.join(' > ');
  };
  const txt = (el, n = 80) => (el.innerText || el.value || el.getAttribute('alt') || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim().slice(0, n);
  const field = (i) => ({ tag: i.tagName.toLowerCase(), type: i.type || '', name: i.name || '', id: i.id || '', placeholder: i.placeholder || '', text: txt(i, 40), visible: vis(i), selector: cssPath(i) });
  const forms = Array.from(document.querySelectorAll('form')).slice(0, 12).map(f => ({
    selector: cssPath(f), action: f.getAttribute('action') || '', method: f.method || 'get',
    fields: Array.from(f.querySelectorAll('input,select,textarea,button')).filter(i => i.type !== 'hidden').slice(0, 25).map(field),
  }));
  const looseInputs = Array.from(document.querySelectorAll('input:not([type=hidden]),textarea,select')).filter(i => !i.closest('form')).slice(0, 20).map(field);
  const buttons = Array.from(document.querySelectorAll('button,input[type=submit],input[type=image],input[type=button],[role=button],a.btn,.btn,.Btn')).filter(vis).slice(0, 40).map(b => ({ text: txt(b, 40), selector: cssPath(b), type: b.type || '' }));
  const links = Array.from(document.querySelectorAll('a[href]')).filter(a => vis(a) && !/^(javascript:|#|mailto:)/.test(a.getAttribute('href'))).slice(0, 220).map(a => ({ text: txt(a, 70), href: a.getAttribute('href'), selector: cssPath(a) }));
  // 繰り返し構造（検索結果一覧の候補）
  const groups = new Map();
  for (const el of document.querySelectorAll('body *')) {
    const p = el.parentElement; if (!p || !vis(el)) continue;
    if (!(el.querySelector('a[href]') || el.tagName === 'A' || el.tagName === 'TR' || el.tagName === 'LI')) continue;
    const key = cssPath(p) + ' > ' + piece(el);
    const g = groups.get(key) || { parent: cssPath(p), child: piece(el), count: 0, sample: '' , textLen: 0};
    g.count++; if (!g.sample) { g.sample = el.outerHTML.replace(/\s+/g, ' ').slice(0, 700); g.textLen = txt(el, 2000).length; }
    groups.set(key, g);
  }
  const repeated = Array.from(groups.values()).filter(g => g.count >= 3).sort((a, b) => b.count - a.count).slice(0, 15);
  // 本文候補（テキスト量の多いブロック）
  const blocks = Array.from(document.querySelectorAll('main,article,section,div,td,pre')).filter(vis).map(el => ({ selector: cssPath(el), textLen: (el.innerText || '').length, sample: txt(el, 160) }))
    .filter(b => b.textLen > 300).sort((a, b) => b.textLen - a.textLen).slice(0, 12);
  return { url: location.href, title: document.title, forms, looseInputs, buttons, links, repeated, textBlocks: blocks, bodyTextLength: (document.body.innerText || '').length };
}
