"""Generate a standalone dedup confirmation dashboard HTML.

Renders all duplicate_groups with their candidate works side-by-side,
provides decision buttons (same_work / not_duplicate / version_of /
translation_of / supersedes / part_of), and writes decisions to
dedup_reviews.json via a download.
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def safe_json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def json_for_script(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return payload.replace("</", "<\\/").replace(" ", "\\u2028").replace(" ", "\\u2029")


def load_dedup_data(library_root: Path) -> dict[str, Any]:
    db_path = library_root / "literature.sqlite"
    with connect_db(db_path) as conn:
        works_rows = conn.execute("SELECT * FROM works ORDER BY id").fetchall()
        works_by_id: dict[str, dict[str, Any]] = {}
        for row in works_rows:
            w = dict(row)
            w["authors"] = safe_json_loads(w.get("authors"), [])
            works_by_id[w["id"]] = w

        sources_rows = conn.execute("SELECT * FROM source_files ORDER BY id").fetchall()
        sources_by_id: dict[str, dict[str, Any]] = {row["id"]: dict(row) for row in sources_rows}

        groups_rows = conn.execute(
            "SELECT * FROM duplicate_groups ORDER BY id"
        ).fetchall()
        candidates_rows = conn.execute(
            "SELECT * FROM duplicate_candidates ORDER BY group_id, id"
        ).fetchall()

        relations_rows = conn.execute(
            "SELECT * FROM work_relations ORDER BY work_id_a, work_id_b"
        ).fetchall()

    # Build groups with enriched candidates
    groups: list[dict[str, Any]] = []
    cands_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in candidates_rows:
        cand = dict(c)
        work = works_by_id.get(cand.get("work_id") or "")
        if work:
            cand["work_title"] = work.get("title") or cand["work_id"]
            cand["work_authors"] = work.get("authors") or []
            cand["work_year"] = work.get("year")
            cand["work_doc_type"] = work.get("doc_type") or ""
            cand["work_language"] = work.get("language") or ""
            cand["work_parse_status"] = work.get("parse_status") or ""
        src = sources_by_id.get(cand.get("source_file_id") or "")
        if src:
            cand["source_original_name"] = src.get("original_name") or ""
            cand["source_relative_path"] = src.get("relative_source_path") or ""
            cand["source_file_size"] = src.get("file_size")
            cand["source_file_ext"] = src.get("file_ext") or ""
        cands_by_group[cand["group_id"]].append(cand)

    for g in groups_rows:
        group = dict(g)
        group["candidates"] = cands_by_group.get(group["id"], [])
        # Collect unique work IDs for pair generation
        work_ids_in_group = sorted(set(
            c["work_id"] for c in group["candidates"] if c.get("work_id")
        ))
        group["work_ids"] = work_ids_in_group
        # Mark exact_sha256 groups as auto-confirmed (they are byte-identical files)
        group["auto_confirmed"] = (group["duplicate_type"] == "exact_sha256")
        # Check if all candidates in this group are reviewed
        all_reviewed = all(bool(c.get("reviewed")) for c in group["candidates"])
        group["all_reviewed"] = all_reviewed
        groups.append(group)

    existing_relations: list[dict[str, Any]] = [dict(r) for r in relations_rows]

    return {
        "generated_at": utc_now(),
        "library_root": str(library_root),
        "total_works": len(works_by_id),
        "total_groups": len(groups),
        "total_candidates": len(candidates_rows),
        "existing_relations": existing_relations,
        "groups": groups,
    }


DECISION_TYPES = [
    ("same_work", "同一作品", "完全相同的文献（不同来源文件）"),
    ("not_duplicate", "非重复", "不同文献，仅标题/摘要相似"),
    ("version_of", "版本关系", "同一作品的不同版本（如 v1/v2）"),
    ("translation_of", "翻译关系", "同一作品的翻译版本"),
    ("supersedes", "取代关系", "A 是 B 的更新/完整版"),
    ("part_of", "部分关系", "A 是 B 的一部分（如附录）"),
    ("quarantine", "隔离", "来源质量不合格（反爬页面/空白/导航页），需重新获取"),
]


CSS = """\
:root {
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
  --same: #16833a;
  --not: #667085;
  --ver: #1f6feb;
  --trans: #7c3aed;
  --super: #9a6700;
  --part: #0d9488;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font: 14px/1.5 "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
}
header {
  position: sticky; top: 0; z-index: 10;
  padding: 14px 18px 10px;
  background: rgba(247, 248, 250, 0.96);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(8px);
}
h1 { font-size: 22px; font-weight: 650; }
.subline { margin-top: 3px; color: var(--muted); font-size: 12px; }
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px; margin-bottom: 14px; padding: 0 18px;
}
.stat {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; padding: 8px 10px; min-height: 50px;
}
.stat b { display: block; font-size: 20px; line-height: 1.2; }
.stat span { color: var(--muted); font-size: 12px; }
.main { padding: 0 18px 18px; }
.filter-bar {
  display: flex; gap: 8px; align-items: center;
  margin-bottom: 12px; flex-wrap: wrap;
}
.filter-bar select, .filter-bar input, .filter-bar button {
  height: 34px; border: 1px solid var(--line); border-radius: 6px;
  background: #fff; color: var(--text); padding: 0 10px; font: inherit;
}
.filter-bar button {
  background: var(--accent); color: #fff; border-color: var(--accent); cursor: pointer;
}
.filter-bar button.secondary {
  background: var(--panel); color: var(--text); border-color: var(--line);
}
.group-card {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; margin-bottom: 14px; overflow: hidden;
}
.group-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; background: #f1f4f8;
  border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: 6px;
}
.group-header .group-id { font-weight: 650; font-size: 15px; }
.group-header .group-type {
  font-size: 12px; padding: 2px 8px; border-radius: 999px;
  background: var(--chip); color: #344054;
}
.group-header .group-count {
  font-size: 12px; color: var(--muted);
}
.cand-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 10px; padding: 12px 14px;
}
.cand-card {
  border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px;
  background: #fafbfc;
}
.cand-title { font-weight: 600; margin-bottom: 4px; word-break: break-word; }
.cand-meta { font-size: 12px; color: var(--muted); }
.cand-meta div { margin-bottom: 2px; }
.cand-sha { font-family: Consolas, monospace; font-size: 11px; color: #475467;
  word-break: break-all; }
.cand-source { font-size: 12px; color: #475467; word-break: break-all; margin-top: 4px; }
.pair-section {
  padding: 12px 14px; border-top: 1px solid var(--line);
}
.pair-label { font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 6px; }
.decision-btns {
  display: flex; gap: 6px; flex-wrap: wrap;
}
.decision-btns button {
  padding: 4px 10px; border-radius: 999px; font-size: 12px;
  border: 1px solid var(--line); cursor: pointer; background: #fff;
  color: var(--text); transition: all .15s;
}
.decision-btns button:hover { filter: brightness(0.95); }
.decision-btns button.selected { color: #fff; font-weight: 600; }
.decision-btns button[data-decision="same_work"].selected { background: var(--same); border-color: var(--same); }
.decision-btns button[data-decision="not_duplicate"].selected { background: var(--not); border-color: var(--not); }
.decision-btns button[data-decision="version_of"].selected { background: var(--ver); border-color: var(--ver); }
.decision-btns button[data-decision="translation_of"].selected { background: var(--trans); border-color: var(--trans); }
.decision-btns button[data-decision="supersedes"].selected { background: var(--super); border-color: var(--super); }
.decision-btns button[data-decision="part_of"].selected { background: var(--part); border-color: var(--part); }
.decision-btns button[data-decision="quarantine"].selected { background: var(--bad); border-color: var(--bad); }
.decision-btns button.skip-btn {
  background: var(--panel); color: var(--muted); border-style: dashed;
}
.pair-note { margin-top: 4px; }
.pair-note input {
  width: 100%; height: 28px; border: 1px solid var(--line);
  border-radius: 4px; padding: 0 8px; font: inherit; font-size: 12px;
}
.status-badge {
  display: inline-block; font-size: 11px; font-weight: 600;
  padding: 1px 6px; border-radius: 999px;
}
.status-badge.decided { background: #dcfce7; color: #15803d; }
.status-badge.pending { background: #fef9c3; color: #92400e; }
.status-badge.skipped { background: #f1f5f9; color: #64748b; }
.status-badge.auto-confirmed { background: #d1fae5; color: #065f46; }
.direction-hint { font-size: 11px; color: var(--muted); margin-left: 4px; }
.download-bar {
  position: sticky; bottom: 0; z-index: 10;
  padding: 10px 18px; background: rgba(247, 248, 250, 0.96);
  border-top: 1px solid var(--line); backdrop-filter: blur(8px);
  display: flex; gap: 10px; align-items: center;
}
.progress-text { font-size: 13px; color: var(--muted); }
.cmd-box {
  flex: 1; min-width: 0; margin-left: 12px;
  padding: 6px 10px; background: #f1f4f8; border: 1px solid var(--line);
  border-radius: 6px; font-family: Consolas, "SFMono-Regular", monospace;
  font-size: 12px; color: #344054; overflow-x: auto; white-space: nowrap;
  user-select: all; cursor: pointer;
}
.cmd-box:hover { background: #e8ecf2; }
.empty { padding: 28px; text-align: center; color: var(--muted);
  background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
@media (max-width: 900px) {
  .cand-grid { grid-template-columns: 1fr; }
}
"""

# JS is kept as a plain string (not an f-string) to avoid brace-escaping issues.
# We inject data via a <script type="application/json"> tag and read it from JS.
# Decisions are automatically persisted in localStorage so they survive page refresh.
# The bottom bar shows the apply command + a JSON export button.
JS_APP = r"""
(function() {
  var STORAGE_KEY = 'literature_dedup_decisions';
  var dataEl = document.getElementById('dedup-data');
  var groups = JSON.parse(dataEl.textContent);
  dataEl.remove();

  var DECISION_TYPES = {{DECISION_TYPES_JSON}};

  // Restore decisions from localStorage
  var decisions = {};
  try {
    var saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      var parsed = JSON.parse(saved);
      if (parsed && typeof parsed === 'object') decisions = parsed;
    }
  } catch(e) {}

  function saveDecisions() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions));
    } catch(e) {}
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, function(ch) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch];
    });
  }

  function getDecisionKeys(group) {
    if (group.duplicate_type === 'exact_sha256') {
      return ['group:' + group.id];
    } else {
      var wids = group.work_ids;
      var keys = [];
      for (var i = 0; i < wids.length; i++) {
        for (var j = i + 1; j < wids.length; j++) {
          keys.push('pair:' + wids[i] + '|' + wids[j]);
        }
      }
      return keys;
    }
  }

  function renderStats() {
    var allKeys = groups.groups.reduce(function(acc, g) { return acc.concat(getDecisionKeys(g)); }, []);
    var decided = allKeys.filter(function(k) { return decisions[k] && decisions[k].type !== 'skip'; }).length;
    var skipped = allKeys.filter(function(k) { return decisions[k] && decisions[k].type === 'skip'; }).length;
    var total = allKeys.length;
    document.getElementById('stats').innerHTML = [
      ['重复组', groups.total_groups],
      ['候选', groups.total_candidates],
      ['自动确认', groups.groups.filter(function(g){ return g.auto_confirmed; }).length],
      ['需审查', groups.groups.filter(function(g){ return !g.auto_confirmed; }).length],
      ['决策对', total],
      ['已决策', decided],
      ['待决策', total - decided - skipped],
    ].map(function(item) {
      return '<div class="stat"><b>' + escapeHtml(item[1]) + '</b><span>' + escapeHtml(item[0]) + '</span></div>';
    }).join('');
    document.getElementById('progressText').textContent = (decided + skipped) + ' / ' + total + ' 已决策';
    // Update command box
    var cmdBox = document.getElementById('cmdBox');
    if (decided + skipped > 0) {
      cmdBox.textContent = 'python scripts/dedup_apply.py --reviews views/dedup_reviews.json';
    } else {
      cmdBox.textContent = '完成决策后运行：';
    }
  }

  function renderGroupList() {
    var typeFilter = document.getElementById('typeFilter').value;
    var statusFilter = document.getElementById('statusFilter').value;
    var query = document.getElementById('search').value.trim().toLowerCase();
    var out = '';

    for (var gi = 0; gi < groups.groups.length; gi++) {
      var group = groups.groups[gi];
      if (typeFilter !== 'all' && group.duplicate_type !== typeFilter) continue;
      if (query) {
        var haystack = group.candidates.map(function(c) {
          return [c.work_id, c.work_title, c.source_original_name, c.group_id, c.reason].join(' ').toLowerCase();
        }).join(' ');
        if (haystack.indexOf(query) === -1) continue;
      }
      var keys = getDecisionKeys(group);
      var allDecided = keys.every(function(k) { return decisions[k]; });
      var someDecided = keys.some(function(k) { return decisions[k]; });
      if (statusFilter === 'needsreview') {
        if (group.auto_confirmed) continue;
      } else if (statusFilter === 'pending') {
        if (someDecided || group.auto_confirmed) continue;
      } else if (statusFilter === 'decided') {
        if (!allDecided || group.auto_confirmed) continue;
      } else if (statusFilter === 'confirmed') {
        if (!group.auto_confirmed) continue;
      }

      var statusLabel, badgeClass, badgeText;
      if (group.auto_confirmed) {
        statusLabel = 'confirmed';
        badgeClass = 'status-badge auto-confirmed';
        badgeText = '已自动确认';
      } else if (allDecided) {
        var allSkip = keys.every(function(k) { return decisions[k] && decisions[k].type === 'skip'; });
        statusLabel = allSkip ? 'skipped' : 'decided';
        badgeClass = allSkip ? 'status-badge skipped' : 'status-badge decided';
        badgeText = allSkip ? '已跳过' : '已决策';
      } else {
        statusLabel = someDecided ? 'partial' : 'pending';
        badgeClass = 'status-badge pending';
        badgeText = someDecided ? '部分决策' : '待决策';
      }

      var typeLabel = group.duplicate_type === 'exact_sha256' ? 'SHA256 完全相同' : '标题相似';
      out += '<div class="group-card" data-group-id="' + escapeHtml(group.id) + '">';
      out += '<div class="group-header"><div>';
      out += '<span class="group-id">' + escapeHtml(group.id) + '</span> ';
      out += '<span class="group-type">' + escapeHtml(typeLabel) + '</span> ';
      out += '<span class="group-count">' + escapeHtml(group.candidates.length) + ' 个来源 · ' + escapeHtml(group.work_ids.length) + ' 个作品</span>';
      out += '</div><span class="' + badgeClass + '">' + escapeHtml(badgeText) + '</span></div>';

      // Candidate cards
      out += '<div class="cand-grid">';
      for (var ci = 0; ci < group.candidates.length; ci++) {
        var cand = group.candidates[ci];
        var srcName = cand.source_original_name || (cand.source_path || '').split(/[\\/]/).pop() || cand.source_file_id || '';
        out += '<div class="cand-card">';
        out += '<div class="cand-title">' + escapeHtml(cand.work_title || cand.work_id || '?') + '</div>';
        out += '<div class="cand-meta">';
        out += '<div>ID: ' + escapeHtml(cand.work_id || '') + '</div>';
        if (cand.work_year) out += '<div>年份: ' + escapeHtml(cand.work_year) + '</div>';
        if (cand.work_doc_type) out += '<div>类型: ' + escapeHtml(cand.work_doc_type) + '</div>';
        if (cand.work_language) out += '<div>语言: ' + escapeHtml(cand.work_language) + '</div>';
        if (cand.work_authors && cand.work_authors.length) out += '<div>作者: ' + escapeHtml(cand.work_authors.join('; ')) + '</div>';
        if (cand.work_parse_status) out += '<div>解析: ' + escapeHtml(cand.work_parse_status) + '</div>';
        out += '</div>';
        if (group.duplicate_type === 'exact_sha256' && group.key) {
          out += '<div class="cand-sha">sha256: ' + escapeHtml(group.key.substring(0, 16)) + '...</div>';
        }
        out += '<div class="cand-source">' + escapeHtml(srcName) + '</div>';
        out += '</div>';
      }
      out += '</div>';

      // Decision section
      if (group.auto_confirmed) {
        out += '<div class="pair-section"><div class="pair-label" style="color:#065f46;">✓ 已自动确认：SHA256 完全相同，属于同一作品的不同来源文件，无需人工审查。</div></div>';
      } else if (group.duplicate_type === 'exact_sha256') {
        var key = 'group:' + group.id;
        var current = decisions[key];
        out += '<div class="pair-section">';
        out += '<div class="pair-label">这组是同一文献的不同来源文件？</div>';
        out += buildDecisionButtons(key, current);
        out += '<div class="pair-note"><input placeholder="备注（可选）" data-key="' + escapeHtml(key) + '" value="' + escapeHtml((current && current.note) || '') + '"></div>';
        out += '</div>';
      } else {
        var wids = group.work_ids;
        for (var i = 0; i < wids.length; i++) {
          for (var j = i + 1; j < wids.length; j++) {
            var pkey = 'pair:' + wids[i] + '|' + wids[j];
            var pcur = decisions[pkey];
            var tA = '', tB = '';
            for (var k = 0; k < group.candidates.length; k++) {
              if (group.candidates[k].work_id === wids[i]) tA = group.candidates[k].work_title || wids[i];
              if (group.candidates[k].work_id === wids[j]) tB = group.candidates[k].work_title || wids[j];
            }
            out += '<div class="pair-section">';
            out += '<div class="pair-label">' + escapeHtml(tA) + ' <span class="direction-hint">→</span> ' + escapeHtml(tB) + '</div>';
            out += buildDecisionButtons(pkey, pcur);
            out += '<div class="pair-note"><input placeholder="备注（可选）" data-key="' + escapeHtml(pkey) + '" value="' + escapeHtml((pcur && pcur.note) || '') + '"></div>';
            out += '</div>';
          }
        }
      }
      out += '</div>';
    }

    if (!out) out = '<div class="empty">没有匹配的重复组</div>';
    document.getElementById('groupList').innerHTML = out;
    wireUp();
  }

  function buildDecisionButtons(key, current) {
    var s = '<div class="decision-btns" data-key="' + escapeHtml(key) + '">';
    for (var i = 0; i < DECISION_TYPES.length; i++) {
      var dt = DECISION_TYPES[i];
      var sel = (current && current.type === dt[0]) ? ' selected' : '';
      s += '<button data-decision="' + escapeHtml(dt[0]) + '" title="' + escapeHtml(dt[2]) + '" class="' + sel + '">' + escapeHtml(dt[1]) + '</button>';
    }
    var skipSel = (current && current.type === 'skip') ? ' selected' : '';
    s += '<button data-decision="skip" class="skip-btn' + skipSel + '" title="暂时跳过">跳过</button>';
    s += '</div>';
    return s;
  }

  function wireUp() {
    var btnGroups = document.querySelectorAll('.decision-btns');
    for (var i = 0; i < btnGroups.length; i++) {
      (function(btns) {
        var buttons = btns.querySelectorAll('button');
        for (var j = 0; j < buttons.length; j++) {
          buttons[j].addEventListener('click', function() {
            var key = btns.getAttribute('data-key');
            var dtype = this.getAttribute('data-decision');
            decisions[key] = { type: dtype, note: '', timestamp: new Date().toISOString() };
            if (dtype !== 'skip') {
              var noteInput = btns.parentElement.querySelector('.pair-note input');
              if (noteInput) decisions[key].note = noteInput.value;
            }
            for (var k = 0; k < buttons.length; k++) buttons[k].classList.remove('selected');
            this.classList.add('selected');
            saveDecisions();
            renderStats();
            renderGroupList();
          });
        }
      })(btnGroups[i]);
    }
    var noteInputs = document.querySelectorAll('.pair-note input');
    for (var n = 0; n < noteInputs.length; n++) {
      noteInputs[n].addEventListener('input', function() {
        var key = this.getAttribute('data-key');
        if (decisions[key]) decisions[key].note = this.value;
        saveDecisions();
      });
    }
  }

  function downloadDecisions() {
    var reviewData = {
      generated_at: groups.generated_at,
      total_groups: groups.total_groups,
      total_decisions: Object.keys(decisions).length,
      decisions: Object.keys(decisions).map(function(key) {
        var val = decisions[key];
        var parts = key.split(':');
        var scope = parts[0];
        var idPart = parts.slice(1).join(':');
        var groupId = '', workIdA = '', workIdB = '';
        if (scope === 'group') {
          groupId = idPart;
          for (var i = 0; i < groups.groups.length; i++) {
            if (groups.groups[i].id === groupId) {
              workIdA = groups.groups[i].work_ids[0] || '';
              workIdB = groups.groups[i].work_ids[1] || groups.groups[i].work_ids[0] || '';
              break;
            }
          }
        } else {
          var pairParts = idPart.split('|');
          workIdA = pairParts[0] || '';
          workIdB = pairParts[1] || '';
          for (var j = 0; j < groups.groups.length; j++) {
            if (groups.groups[j].work_ids.indexOf(workIdA) !== -1 && groups.groups[j].work_ids.indexOf(workIdB) !== -1) {
              groupId = groups.groups[j].id;
              break;
            }
          }
        }
        return {
          key: key, scope: scope, group_id: groupId,
          work_id_a: workIdA, work_id_b: workIdB,
          decision_type: val.type,
          note: val.note || '',
          timestamp: val.timestamp
        };
      })
    };
    var blob = new Blob([JSON.stringify(reviewData, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'dedup_reviews.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  function markAllSkip() {
    for (var i = 0; i < groups.groups.length; i++) {
      var keys = getDecisionKeys(groups.groups[i]);
      for (var j = 0; j < keys.length; j++) {
        if (!decisions[keys[j]]) {
          decisions[keys[j]] = { type: 'skip', note: '', timestamp: new Date().toISOString() };
        }
      }
    }
    saveDecisions();
    renderStats();
    renderGroupList();
  }

  // Populate filters
  var typeSelect = document.getElementById('typeFilter');
  var typeOptions = '<option value="all">类型：全部</option>';
  var types = [];
  for (var i = 0; i < groups.groups.length; i++) {
    if (types.indexOf(groups.groups[i].duplicate_type) === -1) types.push(groups.groups[i].duplicate_type);
  }
  for (var i = 0; i < types.length; i++) {
    var label = types[i] === 'exact_sha256' ? 'SHA256 完全相同' : '标题相似';
    typeOptions += '<option value="' + escapeHtml(types[i]) + '">' + escapeHtml(label) + '</option>';
  }
  typeSelect.innerHTML = typeOptions;

  var statusSelect = document.getElementById('statusFilter');
  statusSelect.innerHTML = '<option value="all">状态：全部</option>' +
    '<option value="needsreview" selected>需审查</option>' +
    '<option value="pending">未决策</option>' +
    '<option value="decided">已决策</option>' +
    '<option value="confirmed">已自动确认</option>';

  document.getElementById('search').addEventListener('input', function() { renderGroupList(); });
  typeSelect.addEventListener('change', function() { renderGroupList(); });
  statusSelect.addEventListener('change', function() { renderGroupList(); });
  document.getElementById('resetBtn').addEventListener('click', function() {
    document.getElementById('search').value = '';
    typeSelect.value = 'all';
    statusSelect.value = 'all';
    renderGroupList();
  });
  document.getElementById('downloadBtn').addEventListener('click', function() {
    // First save to localStorage, then trigger download
    saveDecisions();
    downloadDecisions();
  });
  document.getElementById('markAllBtn').addEventListener('click', markAllSkip);

  // Click command box to copy
  document.getElementById('cmdBox').addEventListener('click', function() {
    var text = this.textContent;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text);
    } else {
      // Fallback: select text
      var range = document.createRange();
      range.selectNodeContents(this);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
  });

  renderStats();
  renderGroupList();
})();
"""


def render_html(data: dict[str, Any]) -> str:
    payload = json_for_script(data)
    generated = html.escape(data["generated_at"])
    sha256_count = sum(1 for g in data["groups"] if g.get("duplicate_type") == "exact_sha256")
    title_count = sum(1 for g in data["groups"] if g.get("duplicate_type") != "exact_sha256")
    decision_types_json = json.dumps(
        [(d[0], d[1], d[2]) for d in DECISION_TYPES], ensure_ascii=False
    )
    js = JS_APP.replace("{{DECISION_TYPES_JSON}}", decision_types_json)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>去重确认 — 文献库</title>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <h1>去重确认</h1>
    <div class="subline">生成时间：{generated} · {data['total_groups']} 个重复组（{sha256_count} SHA256 已自动确认 · {title_count} 标题候选需审查） · {data['total_candidates']} 个候选</div>
  </header>
  <section class="stats" id="stats"></section>
  <div class="main">
    <div class="filter-bar">
      <select id="typeFilter"><option value="all">类型：全部</option></select>
      <select id="statusFilter"><option value="all">状态：全部</option></select>
      <input id="search" type="search" placeholder="搜索标题、ID、sha256">
      <button id="resetBtn" class="secondary" type="button">重置</button>
    </div>
    <div id="groupList"></div>
  </div>
  <div class="download-bar">
    <span class="progress-text" id="progressText">0 / 0 已决策</span>
    <button id="downloadBtn" type="button" style="background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 16px;cursor:pointer;font:inherit;">导出 JSON</button>
    <button id="markAllBtn" type="button" class="secondary" style="border-radius:6px;padding:6px 16px;cursor:pointer;">全部跳过</button>
    <div class="cmd-box" id="cmdBox" title="点击复制命令">完成决策后运行：</div>
  </div>
  <script id="dedup-data" type="application/json">{payload}</script>
  <script>
{js}
  </script>
</body>
</html>"""


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Generate dedup confirmation dashboard.")
    parser.add_argument("--library-root", type=Path, default=default_root)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    library_root = args.library_root.resolve()
    output = args.output or library_root / "views" / "dedup_dashboard.html"
    data = load_dedup_data(library_root)
    html_content = render_html(data)
    write_text_atomic(output, html_content)
    if args.json_out:
        write_text_atomic(args.json_out, json.dumps(data, ensure_ascii=False, indent=2))
    print(f"dedup dashboard written: {output}")
    print(f"  groups: {data['total_groups']}, candidates: {data['total_candidates']}")


if __name__ == "__main__":
    main()