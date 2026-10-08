/**
 * 证据偏移换算与逐字定位工具（证据侧栏共用）。
 *
 * 偏移约定（工单 LL-UX-EVIDENCE-20260914 §6）：
 * - 服务端（Python）offset 是 Unicode 码点索引（str 下标），针对
 *   research_text_snapshots.content_text **原样存储**的文本——包括 \r。
 *   服务端强校验 content[start:end] == quote。
 * - JS 字符串是 UTF-16 码元序列：非 BMP 字符（扩展汉字、emoji 等）占 2 个
 *   码元，直接用 offset 切片会错位。本模块负责码点 → UTF-16 下标换算。
 * - 渲染后的 HTML/DOM 偏移不是原文字符偏移，禁止混用。
 */

/** 把 Python 码点偏移换算为 JS 字符串下标（越界时夹到文本长度）。 */
export function cpOffsetToJsIndex(text, cpOffset) {
  if (!cpOffset || cpOffset <= 0) return 0
  let cp = 0
  let i = 0
  const s = String(text ?? '')
  while (i < s.length) {
    if (cp === cpOffset) return i
    const code = s.codePointAt(i)
    i += code > 0xffff ? 2 : 1
    cp += 1
  }
  return s.length
}

/** 把 JS 字符串下标换算回 Python 码点偏移（证据登记用，页面展示用）。 */
export function jsIndexToCpOffset(text, jsIndex) {
  const s = String(text ?? '')
  const end = Math.max(0, Math.min(jsIndex ?? 0, s.length))
  let cp = 0
  let i = 0
  while (i < end) {
    const code = s.codePointAt(i)
    i += code > 0xffff ? 2 : 1
    cp += 1
  }
  return cp
}

/**
 * 在文本中找 quote 的第 occurrenceIndex（1 起）处出现，返回
 * { start, end }（码点偏移）。找不到第 N 处时返回 null。
 */
export function findQuoteOccurrence(text, quote, occurrenceIndex = 1) {
  const s = String(text ?? '')
  const q = String(quote ?? '')
  if (!q) return null
  let from = 0
  let seen = 0
  while (from <= s.length - q.length) {
    const at = s.indexOf(q, from)
    if (at < 0) break
    seen += 1
    if (seen === occurrenceIndex) {
      return { start: jsIndexToCpOffset(s, at), end: jsIndexToCpOffset(s, at + q.length) }
    }
    from = at + 1
  }
  return null
}

/** quote 在文本中的出现总次数。 */
export function countQuoteOccurrences(text, quote) {
  const s = String(text ?? '')
  const q = String(quote ?? '')
  if (!q) return 0
  let count = 0
  let from = 0
  while (from <= s.length - q.length) {
    const at = s.indexOf(q, from)
    if (at < 0) break
    count += 1
    from = at + 1
  }
  return count
}

/**
 * 侧栏上下文切片：按码点窗口取 quote 前后各 `window` 个码点，
 * 返回 { before, quote, after }，均为 JS 字符串（可直接渲染）。
 */
export function snapshotWindow(text, startCp, endCp, window = 240) {
  const s = String(text ?? '')
  const start = cpOffsetToJsIndex(s, startCp)
  const end = cpOffsetToJsIndex(s, endCp)
  if (end < start) return null
  const beforeStart = cpOffsetToJsIndex(s, Math.max(0, startCp - window))
  const afterEnd = cpOffsetToJsIndex(s, Math.min(s.length, endCp + window))
  return {
    before: s.slice(beforeStart, start),
    quote: s.slice(start, end),
    after: s.slice(end, afterEnd),
    beforeOmitted: beforeStart > 0,
    afterOmitted: afterEnd < s.length,
  }
}
