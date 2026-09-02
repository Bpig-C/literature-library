/**
 * 极简 Markdown 渲染器（纯 JS，无第三方依赖——遵守项目"不引入新依赖"红线）。
 *
 * 用途：WorkDetail 内容预览渲染解析产物 content.md（MinerU/PyMuPDF 产出）。
 * 支持：标题、段落、粗/斜体、行内代码、围栏代码块、图片、链接、
 *       无序/有序列表、引用块、分隔线、管道表格。
 * 安全：所有插值文本先 escapeHtml；URL 走 sanitizeUrl 白名单
 *       （http/https/mailto 与站内相对路径），防解析产物中的标签/脚本注入。
 */

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function sanitizeUrl(url) {
  const u = String(url ?? '').trim()
  if (/^(https?:|mailto:)/i.test(u)) return escapeHtml(u)
  if (u.startsWith('/') || u.startsWith('./')) return escapeHtml(u)
  return '#'
}

function splitRow(line) {
  let s = String(line ?? '').trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  // 单元格内转义竖线 \| 先占位，切分后还原
  const cells = s.replace(/\\\|/g, '\u0001').split('|').map(c => c.replace(/\u0001/g, '|').trim())
  return cells
}

function inline(text, opts = {}) {
  const resolveImageSrc = opts.resolveImageSrc || (s => s)
  const tokens = []
  const stash = (html) => {
    tokens.push(html)
    return `\u0000${tokens.length - 1}\u0000`
  }

  let s = String(text ?? '')

  // 图片 ![alt](src)
  s = s.replace(/!\[([^\]]*)\]\(\s*([^)\s]+)[^)]*\)/g, (m, alt, src) => {
    const url = sanitizeUrl(resolveImageSrc(src))
    return stash(`<img src="${url}" alt="${escapeHtml(alt)}" loading="lazy" class="md-img">`)
  })

  // 行内代码（先于其他格式，避免被粗/斜体改写）
  s = s.replace(/`([^`]+)`/g, (m, c) => stash(`<code class="md-code-inline">${escapeHtml(c)}</code>`))

  // 链接
  s = s.replace(/\[([^\]]+)\]\(\s*([^)\s]+)[^)]*\)/g, (m, label, href) =>
    stash(`<a href="${sanitizeUrl(href)}" target="_blank" rel="noopener noreferrer">${inline(label, opts)}</a>`))

  // 其余文本：转义后处理粗体/斜体
  s = escapeHtml(s)
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>')

  // 下标/上标白名单：MinerU 产物常见 <sub>/<sup>（如引文上标、化学式下标），
  // 转义后为 &lt;sub&gt;...——还原为真实标签正确渲染；其余标签保持转义防注入。
  s = s.replace(/&lt;(\/?)(sub|sup)&gt;/g, '<$1$2>')

  // 还原占位 token
  return s.replace(/\u0000(\d+)\u0000/g, (m, idx) => tokens[Number(idx)] ?? '')
}

function renderTable(header, rows, opts) {
  const th = header.map(c => `<th>${inline(c, opts)}</th>`).join('')
  const trs = rows.map(r => `<tr>${r.map(c => `<td>${inline(c, opts)}</td>`).join('')}</tr>`).join('')
  return `<table class="md-table"><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`
}

function isBlockStart(line) {
  return /^\s*```/.test(line)
    || /^#{1,6}\s/.test(line)
    || /^\s*>/.test(line)
    || /^(\s*)([-*+]|\d+[.)])\s+/.test(line)
    || /^\s*([-*_])\s*(?:\1\s*){2,}$/.test(line)
}

function isTableSeparator(line) {
  return /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes('-')
}

/**
 * 渲染 Markdown 为 HTML 字符串。
 * opts.resolveImageSrc(src) => string：图片 src 改写回调（如相对 images/ 路径
 * 映射到后端静态端点）；不传则保留原 src（仍经 sanitizeUrl 白名单）。
 */
export function renderMarkdown(md, opts = {}) {
  const lines = String(md ?? '').replace(/\r\n?/g, '\n').split('\n')
  const out = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    // 围栏代码块
    if (/^\s*```/.test(line)) {
      const buf = []
      i++
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        buf.push(lines[i])
        i++
      }
      i++ // 跳过收尾 ```（或 EOF）
      out.push(`<pre class="md-code"><code>${escapeHtml(buf.join('\n'))}</code></pre>`)
      continue
    }

    // 标题
    const h = /^(#{1,6})\s+(.*)$/.exec(line)
    if (h) {
      const lv = h[1].length
      out.push(`<h${lv} class="md-h md-h${lv}">${inline(h[2], opts)}</h${lv}>`)
      i++
      continue
    }

    // 分隔线
    if (/^\s*([-*_])\s*(?:\1\s*){2,}$/.test(line)) {
      out.push('<hr class="md-hr">')
      i++
      continue
    }

    // 引用块
    if (/^\s*>/.test(line)) {
      const buf = []
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''))
        i++
      }
      out.push(`<blockquote class="md-quote">${renderMarkdown(buf.join('\n'), opts)}</blockquote>`)
      continue
    }

    // 表格：当前行含 | 且下一行是分隔行
    if (line.includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const header = splitRow(line)
      i += 2
      const rows = []
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
        rows.push(splitRow(lines[i]))
        i++
      }
      out.push(renderTable(header, rows, opts))
      continue
    }

    // 列表（同级扁平，不做嵌套缩进）
    const li = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line)
    if (li) {
      const ordered = /\d/.test(li[2])
      const items = []
      while (i < lines.length) {
        const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i])
        if (!m || /\d/.test(m[2]) !== ordered) break
        items.push(m[3])
        i++
      }
      const tag = ordered ? 'ol' : 'ul'
      out.push(`<${tag} class="md-list">${items.map(it => `<li>${inline(it, opts)}</li>`).join('')}</${tag}>`)
      continue
    }

    // 空行
    if (line.trim() === '') {
      i++
      continue
    }

    // 段落：连续非空、非块起始、非表格行
    const buf = [line]
    i++
    while (
      i < lines.length
      && lines[i].trim() !== ''
      && !isBlockStart(lines[i])
      && !(lines[i].includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1]))
    ) {
      buf.push(lines[i])
      i++
    }
    out.push(`<p class="md-p">${buf.map(l => inline(l, opts)).join('<br>')}</p>`)
  }
  return out.join('\n')
}
