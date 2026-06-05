"""Generate a standalone read-only literature dashboard HTML."""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def safe_json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def rel_path(path: str | None, library_root: Path) -> str:
    if not path:
        return ""
    p = Path(path)
    try:
        return str(p.relative_to(library_root))
    except ValueError:
        return str(p)


def path_uri(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).resolve().as_uri()
    except ValueError:
        return ""


def json_for_script(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return payload.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def load_dashboard_data(library_root: Path) -> dict[str, Any]:
    db_path = library_root / "literature.sqlite"
    ledger_path = library_root / "parse_ledger.json"
    index_path = library_root / "index.json"
    with connect_db(db_path) as conn:
        works = [dict(row) for row in conn.execute("SELECT * FROM works ORDER BY id")]
        sources = [dict(row) for row in conn.execute("SELECT * FROM source_files ORDER BY id")]
        parse_runs = (
            [dict(row) for row in conn.execute("SELECT * FROM literature_parse_runs ORDER BY source_file_id")]
            if table_exists(conn, "literature_parse_runs")
            else []
        )
        artifacts = (
            [dict(row) for row in conn.execute("SELECT * FROM parse_artifacts ORDER BY work_id, source_file_id, id")]
            if table_exists(conn, "parse_artifacts")
            else []
        )
        duplicate_candidates = (
            [dict(row) for row in conn.execute("SELECT * FROM duplicate_candidates ORDER BY group_id, id")]
            if table_exists(conn, "duplicate_candidates")
            else []
        )
        relations = (
            [dict(row) for row in conn.execute("SELECT * FROM work_relations ORDER BY work_id_a, work_id_b")]
            if table_exists(conn, "work_relations")
            else []
        )

    ledger = {"runs": {}}
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    index = {"works": []}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))

    db_source_by_id = {source["id"]: source for source in sources}
    active_sources_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for work in index.get("works", []):
        work_id = work.get("work_id")
        if not work_id:
            continue
        for source in work.get("source_files", []):
            source_id = source.get("source_file_id") or ""
            db_source = db_source_by_id.get(source_id, {})
            library_relative_path = source.get("library_relative_path") or db_source.get("relative_source_path") or ""
            active_path = library_root / library_relative_path if library_relative_path else Path("")
            file_size = active_path.stat().st_size if library_relative_path and active_path.exists() else db_source.get("file_size")
            active_sources_by_work[work_id].append(
                {
                    "id": source_id,
                    "work_id": work_id,
                    "content_sha256": source.get("content_sha256") or db_source.get("content_sha256") or "",
                    "original_name": source.get("original_name") or db_source.get("original_name") or "",
                    "source_path": str(active_path) if library_relative_path else db_source.get("source_path", ""),
                    "relative_library_path": library_relative_path,
                    "file_uri": path_uri(str(active_path)) if library_relative_path else "",
                    "file_size": file_size or "",
                    "file_ext": Path(library_relative_path).suffix.lower() if library_relative_path else db_source.get("file_ext", ""),
                    "source_kind": "active",
                }
            )

    # Fallback for a future DB-only record not yet reflected in index.json.
    for source in sources:
        if active_sources_by_work.get(source["work_id"]) and any(
            item["id"] == source["id"] for item in active_sources_by_work[source["work_id"]]
        ):
            continue
        if str(source.get("source_path") or "").startswith(str(library_root)):
            source["relative_library_path"] = rel_path(source.get("source_path"), library_root)
            source["file_uri"] = path_uri(source.get("source_path"))
            source["source_kind"] = "db_only"
            active_sources_by_work[source["work_id"]].append(source)

    runs_by_source = {run["source_file_id"]: run for run in parse_runs}
    artifacts_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        artifact["relative_file_path"] = rel_path(artifact.get("file_path"), library_root)
        artifact["file_uri"] = path_uri(artifact.get("file_path"))
        artifacts_by_work[artifact["work_id"]].append(artifact)

    dup_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in duplicate_candidates:
        dup_by_work[candidate.get("work_id") or ""].append(candidate)

    relations_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for relation in relations:
        relations_by_work[relation["work_id_a"]].append(relation)
        relations_by_work[relation["work_id_b"]].append(relation)

    ledger_runs = ledger.get("runs", {})
    rows: list[dict[str, Any]] = []
    for work in works:
        work_id = work["id"]
        work_sources = active_sources_by_work.get(work_id, [])
        work_runs = []
        for source in work_sources:
            run = runs_by_source.get(source["id"]) or ledger_runs.get(source["id"], {})
            if run:
                work_runs.append(run)
                content_md_path = run.get("content_md_path")
                source["content_md_path"] = content_md_path or ""
                source["content_md_uri"] = path_uri(content_md_path)
                source["parse_status"] = run.get("status") or ""
            else:
                source["content_md_path"] = ""
                source["content_md_uri"] = ""
                source["parse_status"] = ""

        run_statuses = [run.get("status") for run in work_runs if run.get("status")]
        parse_status = work.get("parse_status") or (run_statuses[0] if run_statuses else "unknown")
        if run_statuses and all(status == "succeeded" for status in run_statuses):
            parse_status = "succeeded"
        elif any(status == "failed" for status in run_statuses):
            parse_status = "failed"
        elif any(status in {"pending", "submitted", "running"} for status in run_statuses):
            parse_status = "pending"

        content_md_count = sum(1 for source in work_sources if source.get("content_md_path"))
        rows.append(
            {
                "id": work_id,
                "title": work.get("title") or work_id,
                "authors": safe_json_loads(work.get("authors"), []),
                "year": work.get("year"),
                "arxiv_id": work.get("arxiv_id") or "",
                "doi": work.get("doi") or "",
                "doc_type": work.get("doc_type") or "",
                "language": work.get("language") or "unknown",
                "metadata_status": work.get("metadata_status") or "",
                "parse_status": parse_status,
                "read_status": work.get("read_status") or "",
                "source_count": len(work_sources),
                "content_md_count": content_md_count,
                "sources": work_sources,
                "artifacts": artifacts_by_work.get(work_id, []),
                "duplicate_candidates": dup_by_work.get(work_id, []),
                "relations": relations_by_work.get(work_id, []),
                "updated_at": work.get("updated_at") or "",
                "created_at": work.get("created_at") or "",
            }
        )

    parse_counter = Counter(row["parse_status"] for row in rows)
    type_counter = Counter(row["doc_type"] or "unknown" for row in rows)
    language_counter = Counter(row["language"] or "unknown" for row in rows)
    content_md_total = sum(row["content_md_count"] for row in rows)

    return {
        "generated_at": utc_now(),
        "library_root": str(library_root),
        "summary": {
            "works": len(rows),
            "source_files": sum(row["source_count"] for row in rows),
            "active_sources": sum(row["source_count"] for row in rows),
            "historical_source_files": len(sources),
            "content_md": content_md_total,
            "parse_runs": len(parse_runs),
            "duplicate_candidates": len(duplicate_candidates),
            "relations": len(relations),
        },
        "parse_status_counts": dict(parse_counter),
        "doc_type_counts": dict(type_counter),
        "language_counts": dict(language_counter),
        "works": rows,
    }


def render_html(data: dict[str, Any]) -> str:
    payload = json_for_script(data)
    generated = html.escape(data["generated_at"])
    root = html.escape(data["library_root"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>文献库台账</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #20242c;
      --muted: #667085;
      --accent: #1f6feb;
      --ok: #16833a;
      --warn: #9a6700;
      --bad: #c32f27;
      --chip: #eef2f7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      padding: 14px 18px 10px;
      background: rgba(247, 248, 250, 0.96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(8px);
    }}
    h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 650;
      letter-spacing: 0;
    }}
    .subline {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 430px;
      gap: 14px;
      padding: 14px 18px 18px;
    }}
    .main, .detail {{
      min-width: 0;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(7, minmax(92px, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      min-height: 58px;
    }}
    .stat b {{
      display: block;
      font-size: 20px;
      line-height: 1.2;
    }}
    .stat span {{
      color: var(--muted);
      font-size: 12px;
    }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(240px, 1fr) 130px 130px 130px 110px;
      gap: 8px;
      margin-bottom: 10px;
    }}
    input, select, button {{
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 0 10px;
      font: inherit;
    }}
    button {{
      cursor: pointer;
      color: #fff;
      border-color: var(--accent);
      background: var(--accent);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px 10px;
      vertical-align: top;
      text-align: left;
    }}
    th {{
      position: sticky;
      top: 79px;
      z-index: 5;
      background: #f1f4f8;
      font-size: 12px;
      color: #3a4250;
      white-space: nowrap;
    }}
    tr {{
      cursor: pointer;
    }}
    tr:hover td, tr.selected td {{
      background: #eef5ff;
    }}
    .title {{
      font-weight: 600;
      max-width: 520px;
    }}
    .muted {{
      color: var(--muted);
    }}
    .tiny {{
      font-size: 12px;
    }}
    .chip {{
      display: inline-block;
      min-width: 0;
      max-width: 100%;
      margin: 0 4px 4px 0;
      padding: 2px 7px;
      border-radius: 999px;
      background: var(--chip);
      color: #344054;
      font-size: 12px;
      white-space: nowrap;
    }}
    .status-succeeded {{ color: var(--ok); font-weight: 650; }}
    .status-pending, .status-running, .status-submitted {{ color: var(--warn); font-weight: 650; }}
    .status-failed {{ color: var(--bad); font-weight: 650; }}
    .detail {{
      position: sticky;
      top: 88px;
      align-self: start;
      max-height: calc(100vh - 106px);
      overflow: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
    }}
    .detail h2 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    .section {{
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .section h3 {{
      margin: 0 0 8px;
      font-size: 13px;
      text-transform: uppercase;
      color: #475467;
      letter-spacing: 0;
    }}
    .kv {{
      display: grid;
      grid-template-columns: 110px minmax(0, 1fr);
      gap: 6px 8px;
      font-size: 13px;
    }}
    .kv div:nth-child(odd) {{
      color: var(--muted);
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
      overflow-wrap: anywhere;
    }}
    a:hover {{
      text-decoration: underline;
    }}
    .path {{
      font-family: Consolas, "SFMono-Regular", monospace;
      font-size: 12px;
      color: #344054;
      overflow-wrap: anywhere;
    }}
    .empty {{
      padding: 28px;
      text-align: center;
      color: var(--muted);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
    }}
    @media (max-width: 1100px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .detail {{ position: static; max-height: none; }}
      .stats {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
      .toolbar {{ grid-template-columns: 1fr 1fr; }}
      th {{ top: 0; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>文献库台账</h1>
    <div class="subline">生成时间：{generated} · 根目录：{root}</div>
  </header>
  <div class="layout">
    <main class="main">
      <section class="stats" id="stats"></section>
      <section class="toolbar">
        <input id="search" type="search" placeholder="搜索标题、作者、ID、arXiv、DOI">
        <select id="statusFilter"></select>
        <select id="typeFilter"></select>
        <select id="languageFilter"></select>
        <button id="resetBtn" type="button">重置</button>
      </section>
      <div class="tiny muted" id="resultCount"></div>
      <div id="tableWrap"></div>
    </main>
    <aside class="detail" id="detail"></aside>
  </div>
  <script id="dashboard-data" type="application/json">{payload}</script>
  <script>
    const data = JSON.parse(document.getElementById('dashboard-data').textContent);
    const state = {{ query: '', status: 'all', docType: 'all', language: 'all', selectedId: null }};
    const works = data.works || [];

    const byId = new Map(works.map(item => [item.id, item]));
    const search = document.getElementById('search');
    const statusFilter = document.getElementById('statusFilter');
    const typeFilter = document.getElementById('typeFilter');
    const languageFilter = document.getElementById('languageFilter');
    const tableWrap = document.getElementById('tableWrap');
    const resultCount = document.getElementById('resultCount');
    const detail = document.getElementById('detail');

    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }}[ch]));
    }}

    function statusClass(status) {{
      return 'status-' + String(status || 'unknown').replace(/[^a-z0-9_-]/gi, '').toLowerCase();
    }}

    function uniqueValues(key) {{
      return [...new Set(works.map(item => item[key] || 'unknown'))].sort((a, b) => String(a).localeCompare(String(b), 'zh-CN'));
    }}

    function fillSelect(select, label, values) {{
      select.innerHTML = `<option value="all">${{label}}：全部</option>` + values.map(value =>
        `<option value="${{escapeHtml(value)}}">${{escapeHtml(label)}}：${{escapeHtml(value)}}</option>`
      ).join('');
    }}

    function renderStats() {{
      const summary = data.summary || {{}};
      const cards = [
        ['Works', summary.works || 0],
        ['Source PDF', summary.active_sources || 0],
        ['content.md', summary.content_md || 0],
        ['Parse runs', summary.parse_runs || 0],
        ['重复候选', summary.duplicate_candidates || 0],
        ['关系', summary.relations || 0],
        ['当前筛选', filteredWorks().length],
      ];
      document.getElementById('stats').innerHTML = cards.map(([label, value]) =>
        `<div class="stat"><b>${{escapeHtml(value)}}</b><span>${{escapeHtml(label)}}</span></div>`
      ).join('');
    }}

    function haystack(item) {{
      return [
        item.id, item.title, item.arxiv_id, item.doi, item.doc_type, item.language,
        ...(item.authors || []),
        ...(item.sources || []).map(source => source.original_name || ''),
      ].join(' ').toLowerCase();
    }}

    function filteredWorks() {{
      const q = state.query.trim().toLowerCase();
      return works.filter(item => {{
        if (state.status !== 'all' && item.parse_status !== state.status) return false;
        if (state.docType !== 'all' && item.doc_type !== state.docType) return false;
        if (state.language !== 'all' && item.language !== state.language) return false;
        if (q && !haystack(item).includes(q)) return false;
        return true;
      }});
    }}

    function renderTable() {{
      const rows = filteredWorks();
      resultCount.textContent = `显示 ${{rows.length}} / ${{works.length}} 篇文献`;
      if (!rows.length) {{
        tableWrap.innerHTML = '<div class="empty">没有匹配的文献</div>';
        renderStats();
        return;
      }}
      tableWrap.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>标题</th>
              <th>年份</th>
              <th>类型</th>
              <th>语言</th>
              <th>解析</th>
              <th>来源</th>
              <th>Markdown</th>
              <th>重复候选</th>
            </tr>
          </thead>
          <tbody>
            ${{rows.map(item => `
              <tr data-id="${{escapeHtml(item.id)}}" class="${{item.id === state.selectedId ? 'selected' : ''}}">
                <td>
                  <div class="title">${{escapeHtml(item.title)}}</div>
                  <div class="tiny muted">${{escapeHtml(item.id)}}</div>
                </td>
                <td>${{escapeHtml(item.year || '')}}</td>
                <td>${{escapeHtml(item.doc_type || '')}}</td>
                <td>${{escapeHtml(item.language || '')}}</td>
                <td class="${{statusClass(item.parse_status)}}">${{escapeHtml(item.parse_status || '')}}</td>
                <td>${{escapeHtml(item.source_count)}}</td>
                <td>${{escapeHtml(item.content_md_count)}}</td>
                <td>${{escapeHtml((item.duplicate_candidates || []).length)}}</td>
              </tr>
            `).join('')}}
          </tbody>
        </table>
      `;
      tableWrap.querySelectorAll('tr[data-id]').forEach(row => {{
        row.addEventListener('click', () => {{
          state.selectedId = row.getAttribute('data-id');
          renderTable();
          renderDetail();
        }});
      }});
      if (!state.selectedId || !byId.has(state.selectedId)) {{
        state.selectedId = rows[0].id;
      }}
      renderStats();
    }}

    function linkOrText(uri, text) {{
      const label = escapeHtml(text || uri || '');
      return uri ? `<a href="${{escapeHtml(uri)}}" target="_blank" rel="noreferrer">${{label}}</a>` : label;
    }}

    function renderDetail() {{
      const item = byId.get(state.selectedId) || filteredWorks()[0] || works[0];
      if (!item) {{
        detail.innerHTML = '<div class="empty">暂无文献</div>';
        return;
      }}
      state.selectedId = item.id;
      const authors = (item.authors || []).length ? item.authors.join('; ') : '未知';
      const sources = (item.sources || []).map(source => `
        <div class="section">
          <h3>${{escapeHtml(source.original_name || source.id)}}</h3>
          <div class="kv">
            <div>source id</div><div class="path">${{escapeHtml(source.id || '')}}</div>
            <div>PDF</div><div>${{linkOrText(source.file_uri, source.relative_library_path || source.source_path)}}</div>
            <div>content.md</div><div>${{linkOrText(source.content_md_uri, source.content_md_path || '未生成')}}</div>
            <div>sha256</div><div class="path">${{escapeHtml(source.content_sha256 || '')}}</div>
            <div>大小</div><div>${{escapeHtml(source.file_size || '')}}</div>
          </div>
        </div>
      `).join('');
      const artifacts = (item.artifacts || []).slice(0, 20).map(artifact => `
        <div class="chip">${{escapeHtml(artifact.type || '')}} · ${{escapeHtml(artifact.parser || '')}}</div>
      `).join('') || '<span class="muted">无</span>';
      const duplicates = (item.duplicate_candidates || []).map(candidate => `
        <div class="path">${{escapeHtml(candidate.group_id || '')}} · score=${{escapeHtml(candidate.score || '')}} · ${{escapeHtml(candidate.reason || '')}}</div>
      `).join('') || '<span class="muted">无</span>';
      const relations = (item.relations || []).map(relation => `
        <div class="path">${{escapeHtml(relation.relation_type || '')}} · ${{escapeHtml(relation.work_id_a || '')}} ↔ ${{escapeHtml(relation.work_id_b || '')}}</div>
      `).join('') || '<span class="muted">无</span>';

      detail.innerHTML = `
        <h2>${{escapeHtml(item.title)}}</h2>
        <div class="tiny muted">${{escapeHtml(item.id)}}</div>
        <div class="section">
          <h3>元数据</h3>
          <div class="kv">
            <div>作者</div><div>${{escapeHtml(authors)}}</div>
            <div>年份</div><div>${{escapeHtml(item.year || '')}}</div>
            <div>类型</div><div>${{escapeHtml(item.doc_type || '')}}</div>
            <div>语言</div><div>${{escapeHtml(item.language || '')}}</div>
            <div>arXiv</div><div>${{escapeHtml(item.arxiv_id || '')}}</div>
            <div>DOI</div><div>${{escapeHtml(item.doi || '')}}</div>
            <div>元数据状态</div><div>${{escapeHtml(item.metadata_status || '')}}</div>
            <div>解析状态</div><div class="${{statusClass(item.parse_status)}}">${{escapeHtml(item.parse_status || '')}}</div>
            <div>阅读状态</div><div>${{escapeHtml(item.read_status || '')}}</div>
          </div>
        </div>
        ${{sources}}
        <div class="section">
          <h3>解析产物</h3>
          ${{artifacts}}
        </div>
        <div class="section">
          <h3>重复候选</h3>
          ${{duplicates}}
        </div>
        <div class="section">
          <h3>文献关系</h3>
          ${{relations}}
        </div>
      `;
    }}

    fillSelect(statusFilter, '解析', uniqueValues('parse_status'));
    fillSelect(typeFilter, '类型', uniqueValues('doc_type'));
    fillSelect(languageFilter, '语言', uniqueValues('language'));
    search.addEventListener('input', event => {{ state.query = event.target.value; renderTable(); renderDetail(); }});
    statusFilter.addEventListener('change', event => {{ state.status = event.target.value; renderTable(); renderDetail(); }});
    typeFilter.addEventListener('change', event => {{ state.docType = event.target.value; renderTable(); renderDetail(); }});
    languageFilter.addEventListener('change', event => {{ state.language = event.target.value; renderTable(); renderDetail(); }});
    document.getElementById('resetBtn').addEventListener('click', () => {{
      state.query = ''; state.status = 'all'; state.docType = 'all'; state.language = 'all';
      search.value = ''; statusFilter.value = 'all'; typeFilter.value = 'all'; languageFilter.value = 'all';
      renderTable(); renderDetail();
    }});
    renderTable();
    renderDetail();
  </script>
</body>
</html>
"""


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Generate a read-only literature dashboard.")
    parser.add_argument("--library-root", type=Path, default=default_root)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    library_root = args.library_root.resolve()
    output = args.output or library_root / "views" / "library_dashboard.html"
    data = load_dashboard_data(library_root)
    write_text_atomic(output, render_html(data))
    if args.json_out:
        write_text_atomic(args.json_out, json.dumps(data, ensure_ascii=False, indent=2))
    print(f"dashboard written: {output}")
    print(
        "summary: "
        + json.dumps(data["summary"], ensure_ascii=False, sort_keys=True)
    )


if __name__ == "__main__":
    main()
