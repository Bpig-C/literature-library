import MarkdownIt from 'markdown-it'
import { renderMarkdown } from './markdown'
import { cpOffsetToJsIndex } from './offsets'

const parser = new MarkdownIt({ html: true })

// Block maps are computed from the original snapshot's lines. CRLF is retained
// in the offsets even though markdown-it normalizes it while parsing.
export function renderEvidenceMarkdown(text, evidence) {
  const start = evidence?.start_offset
  const end = evidence?.end_offset
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > [...text].length) return null
  const from = cpOffsetToJsIndex(text, start)
  const to = cpOffsetToJsIndex(text, end)
  if (text.slice(from, to) !== evidence.quote) return null
  const lines = [0]
  for (const m of text.matchAll(/\r\n|\r|\n/g)) lines.push(m.index + m[0].length)
  const tokens = parser.parse(text, {})
  const cuts = new Set([0, text.length])
  for (const token of tokens) {
    if (token.level === 0 && token.map) {
      cuts.add(lines[token.map[0]] ?? text.length)
      cuts.add(lines[token.map[1]] ?? text.length)
    }
  }
  const boundaries = [...cuts].sort((a, b) => a - b)
  let exact = false
  const blocks = []
  for (let i = 0; i < boundaries.length - 1; i++) {
    const a = boundaries[i], b = boundaries[i + 1]
    const source = text.slice(a, b)
    if (!source.trim()) continue
    const selected = a < to && b > from
    const container = document.createElement('div')
    container.innerHTML = renderMarkdown(source)
    // A work-level "latest image" URL is not a fixed-snapshot asset binding.
    for (const img of container.querySelectorAll('img')) {
      const note = document.createElement('p')
      note.className = 'snapshot-image-note'
      note.textContent = `图片引用：${img.getAttribute('alt') || img.getAttribute('src') || '图片'}（此快照未提供固定图片资源映射，请回查原件）`
      img.replaceWith(note)
    }
    // Only highlight a text node when the quote is unique in both this source
    // block and its rendered text. Otherwise show the honest block-level map.
    if (selected && from >= a && to <= b && source.indexOf(evidence.quote) === source.lastIndexOf(evidence.quote)) {
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
      const matches = []
      while (walker.nextNode()) {
        const node = walker.currentNode
        if (node.parentElement.closest('.katex, script, style')) continue
        const at = node.data.indexOf(evidence.quote)
        if (at >= 0) matches.push({ node, at })
      }
      if (matches.length === 1 && container.textContent.indexOf(evidence.quote) === container.textContent.lastIndexOf(evidence.quote)) {
        const { node, at } = matches[0]
        const range = document.createRange()
        range.setStart(node, at)
        range.setEnd(node, at + evidence.quote.length)
        const mark = document.createElement('mark')
        mark.className = 'evidence-exact'
        range.surroundContents(mark)
        exact = true
      }
    }
    blocks.push(`<section class="snapshot-block${selected ? ' evidence-target' : ''}">${container.innerHTML}</section>`)
  }
  return { html: blocks.join(''), precision: exact ? 'text' : 'block' }
}
