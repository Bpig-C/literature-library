# -*- coding: utf-8 -*-
"""19 篇 W-arxiv 文献的人读核实回填（2026-09-02，逐篇读解析稿刊头+arXiv stamp 证据）。

- title 仅覆盖 ID 式坏标题或与文档不一致者（doc-exact）；
- authors 覆盖截断/损坏/匿名模板值；
- abstract 用确定性正则切片（Abstract 段原文），不经 LLM；
- venue 无发表 banner 证据时一律 'arXiv preprint'。
"""
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB = r"D:\02_academic\doctoral\literature_library\literature.sqlite"

ARXIV = "arXiv preprint"
V = {
 "W-arxiv-1706.03762": dict(
   title="Attention Is All You Need",
   authors=["Ashish Vaswani","Noam Shazeer","Niki Parmar","Jakob Uszkoreit","Llion Jones","Aidan N. Gomez","Łukasz Kaiser","Illia Polosukhin"],
   year=2017, venue=ARXIV, abs_=True,
   note="8 作者刊头逐一核实；无发表 banner"),
 "W-arxiv-1810.04805": dict(
   title="BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
   authors=["Jacob Devlin","Ming-Wei Chang","Kenton Lee","Kristina Toutanova"],
   year=2018, venue=ARXIV, abs_=True,
   note="原title 'smoke - bert - 1810.04805' 为坏标题；LLM 曾抽 year=2019（模型知识而非文档），按 arXiv 1810=2018-10 修正"),
 "W-arxiv-2105.14111": dict(
   title="Goal Misgeneralization in Deep Reinforcement Learning",
   authors=["Lauro Langosco","Jack Koch","Lee Sharkey","Jacob Pfau","Laurent Orseau","David Krueger"],
   venue=ARXIV, abs_=True,
   note="覆盖 'Anonymous Submission' 模板作者名；ICML 模板但无发表 banner，venue 从文档证据"),
 "W-arxiv-2210.01790": dict(
   title="Goal Misgeneralization: Why Correct Specifications Aren\u2019t Enough For Correct Goals",
   authors=["Rohin Shah","Vikrant Varma","Ramana Kumar","Mary Phuong","Victoria Krakovna","Jonathan Uesato","Zac Kenton"],
   year=2022, venue=ARXIV, abs_=True, note=None),
 "W-arxiv-2402.07688": dict(
   title="CyberMetric: A Benchmark Dataset based on Retrieval-Augmented Generation for Evaluating LLMs in Cybersecurity Knowledge",
   authors=["Norbert Tihanyi","Mohamed Amine Ferrag","Ridhi Jain","Tamas Bisztray","Merouan Debbah".replace("Merouan","Merouane")],
   year=2024, venue=ARXIV, abs_=True,
   note="原title 'CyberMetric' 不完整"),
 "W-arxiv-2406.10162": dict(
   title="Sycophancy to Subterfuge: Investigating Reward Tampering in Language Models",
   authors=["Carson Denison","Monte MacDiarmid","Fazl Barez","David Duvenaud","Shauna Kravec","Samuel Marks","Nicholas Schiefer","Ryan Soklaski","Alex Tamkin","Jared Kaplan","Buck Shlegeris","Samuel R. Bowman","Ethan Perez","Evan Hubinger"],
   year=2024, venue=ARXIV, abs_=True, note=None),
 "W-arxiv-2501.17805": dict(
   title_zh="国际人工智能安全报告", venue="International AI Safety Report",
   note="本地 PDF 为中文版（封面两行题名取首行）；LLM 曾把文件号 'DSIT 2025/001' 当 venue"),
 "W-arxiv-2503.04746": dict(
   title="Emerging Practices in Frontier AI Safety Frameworks",
   authors=["Marie Davidsen Buhl","Ben Bucknall","Tammy Masterson"],
   venue="UK AI Safety Institute Technical Report",
   note="原title 介词与文档不符（for→in）；原 authors 仅 1/3 人；AISI 刊头徽标核实"),
 "W-arxiv-2506.19248": dict(year=2025, venue=ARXIV, abs_=True, note=None),
 "W-arxiv-2507.03068": dict(year=2025, venue=ARXIV, abs_=True,
   note="LLM 曾抽 year=2024，arXiv stamp 2507=2025-07，修正"),
 "W-arxiv-2507.06261": dict(
   authors=["Gemini Team, Google"], year=2025, venue=ARXIV,
   note="LLM 抽作者 0 人；原 authors 为 dict 结构，规范化；LLM venue 曾混入类别 'cs.CL'"),
 "W-arxiv-2507.16534": dict(
   authors=["Shanghai Artificial Intelligence Laboratory"], year=2025, venue=ARXIV,
   note="原 authors 为入库事故值 '[object Object]'，按刊头机构署名修复"),
 "W-arxiv-2511.05524": dict(year=2025, venue=ARXIV, abs_=True,
   note="文档内印日期 November 11, 2025"),
 "W-arxiv-2511.18397": dict(year=2025, venue=ARXIV, abs_=True,
   note="22 作者存量完整，未改动"),
 "W-arxiv-2512.01166": dict(
   authors=["Lily Stelling","Malcolm Murray","Bruno Galizzi","Max Schaffelder","Siméon Campos","Henry Papadatos"],
   year=2026, venue=ARXIV,
   note="arXiv stamp v5 30 Apr 2026；dict 式 authors 规范化"),
 "W-arxiv-2602.14457": dict(
   authors=["Dongrui Liu","Yi Yu","Jie Zhang","Guanxu Chen","Qihao Lin","Hanxi Zhu","Lige Huang","Yijin Zhou","Peng Wang","Shuai Shao","Boxuan Zhang","Zicheng Liu","Jingwei Sun","Yu Li","Yuejin Xie","Jiaxuan Guo","Jia Xu","Chaochao Lu","Bowen Zhou","Xia Hu","Jing Shao"],
   year=2026, venue=ARXIV,
   note="21 作者刊头逐一核实（SafeWork v1.5, Last updated 15 Feb 2026）；与 2507.16534 为同框架不同版本"),
 "W-arxiv-2602.21012": dict(venue="International AI Safety Report",
   note="封面 February 2026；LLM venue 'DSIT Research Series' 不取，机构系列名以封面为准"),
 "W-arxiv-2603.07427": dict(year=2026, venue=ARXIV, abs_=True, note=None),
}

ABS_PAT = re.compile(
    r"(?:^#+\s*(?:abstract)|^abstract)\s*[:.]?\s*\n?(.*?)(?=^\s*#\s|\n\s*\n\s*(?:1\s+|keywords|index terms|introduction)|^\s*(?:1|I)\s*[.、]?\s+(?:introduction|引言))",
    re.IGNORECASE | re.DOTALL | re.MULTILINE)

def slice_abstract(path: str) -> str | None:
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = ABS_PAT.search(txt)
    if not m:
        return None
    s = re.sub(r"\s+", " ", m.group(1)).strip(" .;")
    return (s + ".") if s else None

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc).isoformat(timespec="seconds")
stats = {"title": 0, "authors": 0, "year": 0, "venue": 0, "abstract": 0, "rows": 0}

for wid, v in V.items():
    w = dict(conn.execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone())
    sets, params = [], []

    def put(col, val):
        sets.append(f"{col} = ?"); params.append(val)

    if v.get("title") and w["title"] != v["title"]:
        put("title", v["title"]); stats["title"] += 1
    if v.get("title_zh") and (w.get("title_zh") or "").strip() != v["title_zh"]:
        put("title_zh", v["title_zh"]); stats["title"] += 1
    if v.get("authors"):
        cur = w["authors"] or ""
        if cur.startswith("[{") or "[object Object]" in cur or "Anonymous" in cur or len(json.loads(cur)) < len(v["authors"]):
            put("authors", json.dumps(v["authors"], ensure_ascii=False)); stats["authors"] += 1
    if v.get("year") and not w["year"]:
        put("year", v["year"]); stats["year"] += 1
    if v.get("venue") and not (w["venue"] or "").strip():
        put("venue", v["venue"]); stats["venue"] += 1
    if v.get("abs_") and not (w["abstract"] or "").strip():
        parse = conn.execute("SELECT content_md_path FROM literature_parse_runs WHERE work_id=? AND status='succeeded' AND content_md_path IS NOT NULL AND content_md_path!='' LIMIT 1", (wid,)).fetchone()
        ab = slice_abstract(parse["content_md_path"]) if parse else None
        if ab:
            put("abstract", ab); stats["abstract"] += 1

    if sets:
        put("updated_at", "datetime('now')")
        if w.get("metadata_status") in (None, "", "missing", "auto"):
            sets.append("metadata_status = 'human_confirmed'")
        params.append(wid)
        sets_clause = ", ".join(s for s in sets)
        conn.execute(f"UPDATE works SET {sets_clause} WHERE id = ?", params)

    if not conn.execute("SELECT COUNT(*) c FROM metadata_extractions WHERE work_id=? AND review_status='approved'", (wid,)).fetchone()["c"]:
        parse = conn.execute("SELECT content_md_path FROM literature_parse_runs WHERE work_id=? AND status='succeeded' AND content_md_path IS NOT NULL AND content_md_path!='' LIMIT 1", (wid,)).fetchone()
        extracted = {"title": v.get("title") or w["title"], "venue": v.get("venue") or w["venue"],
                     "authors": v.get("authors") or json.loads(w["authors"] or "[]"),
                     "date": str(v.get("year") or w["year"])}
        extracted = {k: x for k, x in extracted.items() if x}
        conn.execute(
            "INSERT INTO metadata_extractions (id, work_id, model_name, content_md_path, "
            " input_chars, input_tokens_est, raw_response, extracted_json, confidence_json, "
            " applied, applied_at, created_at, review_status, review_note, reviewed_at, "
            " risk_level, risk_score, risk_reasons, review_source, fix_action) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("ME-" + uuid.uuid4().hex[:12], wid, "human-verified", parse["content_md_path"] if parse else "",
             0, 0, None, json.dumps(extracted, ensure_ascii=False),
             json.dumps({k: "high" for k in extracted}, ensure_ascii=False),
             1, now, now, "approved", (v.get("note") or "") + "；2026-09-02 人读解析稿刊头核实", now,
             "low", 0, "[]", "human", "manual_verify_20260902"))
        stats["rows"] += 1
    conn.commit()
    print("OK", wid)

print("\n统计:", stats)
conn.close()
