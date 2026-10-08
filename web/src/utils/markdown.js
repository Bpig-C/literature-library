/**
 * 统一 Markdown 渲染器（研究展示与证据侧栏共用）。
 *
 * 渲染管线：数学预提取 → markdown-it（html:true，保留解析产物中的
 * HTML 表格与 rowspan/colspan 结构）→ DOMPurify 消毒（脚本/事件属性/
 * 危险 URL 一律剥除）→ KaTeX 还原数学占位符。
 *
 * 数学在消毒之后再渲染：KaTeX 自身对源文本做转义且默认 trust:false，
 * 其输出不经过 DOMPurify 以免破坏排版结构。
 *
 * 依赖：markdown-it、katex、dompurify（工单 LL-UX-EVIDENCE-20260914 明确
 * 授权以可维护依赖替代继续扩大的手写解析器；三者均为高维护活跃度的
 * 上游库；渲染后仍执行消毒与反例测试）。
 */
import MarkdownIt from 'markdown-it'
import katex from 'katex'
import DOMPurify from 'dompurify'
import 'katex/dist/katex.min.css'

const mdit = new MarkdownIt({ html: true, linkify: false, breaks: true })

// 解析产物中的站外链接在新标签打开；站内相对路径同样保持可点。
const defaultLinkOpen =
  mdit.renderer.rules.link_open ||
  ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))
mdit.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

// 表格统一在消毒后包横向滚动容器（见 renderMarkdown 末尾），
// 管道表格与解析产物中的 HTML 表格走同一条路径。

/**
 * 数学扫描：跳过围栏代码块、行内代码与转义 \$，避免代码里的
 * 公式符号被当作公式渲染（验收场景 2）。返回 { text, items }，
 * items[i] = { source, display }，文本中使用本次生成的随机前缀，避免实体解码后的用户文本碰撞。
 */
export function extractMath(md) {
  const s = String(md ?? '').replace(/\r\n?/g, '\n')
  const items = []
  let prefix = 'LITMATH' + Array.from(crypto.getRandomValues(new Uint32Array(4)), n => n.toString(16)).join('') + 'Q'
  while (s.includes(prefix)) prefix += 'X'
  // 依次匹配：围栏代码块 / 行内代码 / 块级 $$..$$ 与 \[..\] / 行内 $..$ 与 \(..\)
  const scan =
    /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$))|(`+[^`\n]*`+)|(\$\$[\s\S]+?\$\$)|(\\\[([\s\S]+?)\\\])|(\\\(([\s\S]+?)\\\))|(\$)(?!\s)((?:\\.|[^$\\\n])+?)\$/g
  let out = ''
  let last = 0
  for (const m of s.matchAll(scan)) {
    if (m[1] || m[2]) continue // 代码原样保留，交给 markdown-it 渲染
    let source = ''
    let display = false
    if (m[3]) { source = m[3].slice(2, -2); display = true }
    else if (m[4]) { source = m[5]; display = true }
    else if (m[6]) { source = m[7]; display = false }
    else if (m[8]) {
      const body = m[9] ?? ''
      // 行内公式收尾不能是空白（排除 "cost $5 and $6" 一类货币误配）
      if (!body || /\s$/.test(body) || /^\s/.test(body)) continue
      source = body
    }
    if (!source.trim()) continue
    items.push({ source, display })
    out += s.slice(last, m.index)
    // 纯字母占位符：NUL 等控制字符会被 markdown-it/DOMPurify 改写，
    // 普通字母 token 能原样穿过渲染与消毒两个阶段。
    out += `${prefix}${items.length - 1}ZEND`
    last = m.index + m[0].length
  }
  out += s.slice(last)
  return { text: out, items, prefix }
}

function renderMathItem(item) {
  let html
  try {
    html = katex.renderToString(item.source, {
      displayMode: item.display,
      throwOnError: false,
      strict: false,
      trust: false,
      output: 'htmlAndMathml',
    })
  } catch {
    // katex 已设置 throwOnError:false，这里兜底：源码原样可见
    const esc = item.source.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    html = `<code class="md-math-fallback">${esc}</code>`
  }
  const cls = item.display ? 'md-math md-math-block' : 'md-math md-math-inline'
  const title = `公式源码：${item.source}`
  return `<span class="${cls}" title="${title.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')}">${html}</span>`
}

const PURIFY_CONFIG = {
  ADD_ATTR: ['target', 'rowspan', 'colspan', 'abbr', 'scope', 'align', 'valign'],
  FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'base'],
  FORBID_ATTR: ['onerror', 'onload', 'onclick'],
}

function restoreMath(html, items, prefix) {
  const template = document.createElement('template')
  template.innerHTML = html
  const pattern = new RegExp(`${prefix}([0-9]+)ZEND`, 'g')
  for (const el of template.content.querySelectorAll('*')) {
    for (const attr of [...el.attributes]) {
      el.setAttribute(attr.name, attr.value.replace(pattern, (_, index) => items[Number(index)]?.source || ''))
    }
  }
  template.innerHTML = DOMPurify.sanitize(template.innerHTML, PURIFY_CONFIG)
  const walker = document.createTreeWalker(template.content, document.defaultView.NodeFilter.SHOW_TEXT)
  const nodes = []
  while (walker.nextNode()) nodes.push(walker.currentNode)
  for (const node of nodes) {
    if (node.parentElement?.closest('code, pre')) continue
    const matches = [...node.data.matchAll(pattern)]
    if (!matches.length) continue
    const fragment = document.createDocumentFragment()
    let last = 0
    for (const match of matches) {
      fragment.append(document.createTextNode(node.data.slice(last, match.index)))
      const math = document.createElement('template')
      math.innerHTML = renderMathItem(items[Number(match[1])])
      fragment.append(math.content)
      last = match.index + match[0].length
    }
    fragment.append(document.createTextNode(node.data.slice(last)))
    node.replaceWith(fragment)
  }
  return template.innerHTML
}

/**
 * 渲染 Markdown 为可直接 v-html 的 HTML 字符串。
 * opts.resolveImageSrc(src) => string：图片 src 改写回调（如相对 images/
 * 路径映射到后端静态端点）；不传则保留原 src（仍经 DOMPurify URL 检查）。
 */
export function renderMarkdown(md, opts = {}) {
  const { text, items, prefix } = extractMath(md)
  const resolveImageSrc = opts.resolveImageSrc || (src => src)
  const env = {}
  // 图片 src 改写：渲染后统一替换，避免逐 token 干预
  let html = mdit.render(text, env)
  html = html.replace(/<img[^>]*src="([^"]*)"[^>]*>/g, (tag, src) => {
    const resolved = resolveImageSrc(src)
    if (resolved === src) return tag
    return tag.replace(/src="([^"]*)"/, `src="${String(resolved).replace(/"/g, '&quot;')}"`)
  })
  html = DOMPurify.sanitize(html, PURIFY_CONFIG)
  // 管道表格与 HTML 表格统一包横向滚动容器（在消毒后进行，避免被剥离）；
  // 宽表在容器内滚动，不撑破页面。
  html = html.replace(/<table(\s|>)/g, '<div class="md-table-wrap"><table$1')
  html = html.replace(/<\/table>/g, '</table></div>')
  return restoreMath(html, items, prefix)
}
