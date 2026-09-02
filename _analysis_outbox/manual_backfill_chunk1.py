# -*- coding: utf-8 -*-
"""人读核实回填 · 第 1 批（24 篇，2026-09-02 逐篇读解析稿刊头）。
title 只在标记 overwrite 时写；authors 只在标记 overwrite 或现值为空/损坏时写；
其余字段仅填空。每篇插入 approved human-verified 溯源行。
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

DB = r"D:\02_academic\doctoral\literature_library\literature.sqlite"
ARXIV = "arXiv preprint"

# wid: dict(title=, title_overwrite=bool, authors=, authors_overwrite=bool,
#           year=, venue=, arxiv_id=, title_zh=, note=)
V = {
 "W-arxiv-2603.18245": dict(authors=["Xuan Chen","Lu Yan","Ruqi Zhang","Xiangyu Zhang"], year=2026, venue=ARXIV, note="4 作者刊头核实（Purdue）"),
 "W-arxiv-2608.11274": dict(authors=["Albus W. Ng","Yi Han","Jusheng Zhang","Wenhao Wang"], year=2026, venue=ARXIV, note=None),
 "W-arxiv-2608.15286": dict(authors=["Shiven Khurdi"], year=2026, venue=ARXIV, note=None),
 "W-sha-00f6f2c00aba": dict(authors=["Mary Phuong","Roland S. Zimmermann","Ziyue Wang","David Lindner","Victoria Krakovna","Sarah Cogan","Allan Dafoe","Lewis Ho","Rohin Shah"], authors_overwrite=True, year=2025, venue="Google DeepMind", note="封面印日期 2025-7-4；9 作者含并列一作"),
 "W-sha-020b5130e2d6": dict(authors=["Stefan Marksteiner","Christoph Schmittner","Korbinian Christl","Dejan Ničković","Mikael Sjödin","Marjan Sirjani"], authors_overwrite=True, note="6 作者核实；正文日期证据不明确（'December 05, 2023' 疑为引文），year/venue 留空待查"),
 "W-sha-0577019513c6": dict(authors=["Center for AI Standards and Innovation (CAISI), NIST"], year=2025, venue="NIST CAISI Report", note="正文印 June 3, 2025"),
 "W-sha-05e46bff6988": dict(authors=["Anthropic"], year=2026, venue="Anthropic System Card", note="封面印 June 30, 2026"),
 "W-sha-06811e2d0e7a": dict(authors=["Kimi Team"], venue="Kimi Technical Report", note="封面 'TECHNICAL REPORT OF KIMI K2.5'"),
 "W-sha-0739b5d4b8da": dict(authors=["Chen Yueh-Han","Robert McCarthy","Bruce W. Lee","He He","Ian Kivlichan","Bowen Baker","Micah Carroll","Tomek Korbak"], authors_overwrite=True, note="8 作者核实；正文无日期证据，year 留空"),
 "W-sha-07ed1314d14f": dict(arxiv_id="2604.21964", venue=ARXIV, note="arXiv stamp 2604.21964v1 23 Apr 2026"),
 "W-sha-0910d09cb1b2": dict(authors=["Scale AI"], venue="Scale AI Blog", note="博客索引页捕获，正文无日期，year 留空"),
 "W-sha-0a6f0686f123": dict(note="4 作者/2024 存量已有；正文无发表 banner，venue 留空"),
 "W-sha-0aa581ac3614": dict(title="全国网络安全标准化技术委员会官网（TC260）— 首页", title_overwrite=True,
   authors=["全国网络安全标准化技术委员会（TC260）"], venue="TC260 官网", year=2026,
   note="原 title '首页' 无信息量；页内新闻最新 2026-06，按捕获期记 2026"),
 "W-sha-0ab8b3b38688": dict(authors=["OWASP"], venue="OWASP AI Testing Guide", note=None),
 "W-sha-0ad431682c60": dict(authors=["Christina Q. Knight","Kaustubh Deshpande","Ved Sirdeshmukh","Meher Mankikar","Scale Red Team","SEAL Research Team","Julian Michael"], authors_overwrite=True,
   year=2025, venue=ARXIV, arxiv_id="2506.14922", note="解析稿含 arXiv stamp 2506.14922v2 24 Jun 2025"),
 "W-sha-0b9080d64e74": dict(authors=["xAI"], venue="xAI Model Card", note="印 Last updated September 19, 2025"),
 "W-sha-0ce66a1763d6": dict(title="τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains", title_overwrite=True,
   authors=["Shunyu Yao","Noah Shinn","Pedram Razavi","Karthik Narasimhan"], authors_overwrite=True,
   year=2024, venue=ARXIV, arxiv_id="2406.12045", note="解析稿含 arXiv stamp 2406.12045v1；原 title 'Yao et al 2024 tau bench' 为坏标题"),
 "W-sha-0d306c6ca09b": dict(authors=["华为云"], venue="华为云社区", year=2024, note="印 发表于 2024/03/15"),
 "W-sha-0ed423cfda34": dict(authors=["National Institute of Standards and Technology (NIST)"], venue="NIST AI RMF Crosswalk", note="NIST AI RMF 1.0 与 ISO/IEC 23894:2023 对照表；正文无日期，year 留空"),
 "W-sha-0f96616fbebf": dict(authors=["Zhexin Zhang","Leqi Lei","Lindong Wu","Rui Sun","Yongkang Huang","Chong Long","Xiao Liu","Xuanyu Lei","Jie Tang","Minlie Huang"], authors_overwrite=True,
   arxiv_id="2309.07045", note="10 作者核实；arXiv stamp 2309.07045v2；存量 year=2024 保留（可能对应发表年），venue 留空"),
 "W-sha-112e092d67f8": dict(note="该 work 是 PropensityBench 的'知识提取'阅读笔记（notes 文档），非论文本体；论文本体为 W-sha-a2c6b17bc301。建议用户决定是否作为重复项合并"),
 "W-sha-1152b10cb288": dict(authors=["US AI Safety Institute (NIST)","UK AI Safety Institute (DSIT)"], venue="US AISI–UK AISI Joint Pre-Deployment Test Report", note="封面印 December 2024"),
 "W-sha-14a48e4ef052": dict(authors=["Google DeepMind"], venue="Google Frontier Safety Framework v2.0", note="封面印 4th February 2025"),
 "W-sha-1cd9a5246866": dict(authors=["Yassine Essifi"], note="博客文章，页眉 'Frontpage'，25th Apr 2026；站点全名未核实，venue 留空"),
}

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc).isoformat(timespec="seconds")
stats = {"title": 0, "authors": 0, "year": 0, "venue": 0, "arxiv": 0, "rows": 0}

for wid, v in V.items():
    w = dict(conn.execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone())
    if not w:
        print("MISSING", wid); continue
    sets, params = [], []
    def put(c, val): sets.append(f"{c} = ?"); params.append(val)

    if v.get("title") and (v.get("title_overwrite") or not (w["title"] or "").strip()):
        put("title", v["title"]); stats["title"] += 1
    if v.get("title_zh") and not (w.get("title_zh") or "").strip():
        put("title_zh", v["title_zh"]); stats["title"] += 1
    if v.get("authors"):
        cur = w["authors"] or ""
        bad = (not cur.strip()) or cur == "[]" or cur.startswith("[{") or "[object Object]" in cur
        if bad or (v.get("authors_overwrite") and cur != json.dumps(v["authors"], ensure_ascii=False)):
            put("authors", json.dumps(v["authors"], ensure_ascii=False)); stats["authors"] += 1
    if v.get("year") and not w["year"]:
        put("year", v["year"]); stats["year"] += 1
    if v.get("venue") and not (w["venue"] or "").strip():
        put("venue", v["venue"]); stats["venue"] += 1
    if v.get("arxiv_id") and not (w["arxiv_id"] or "").strip():
        put("arxiv_id", v["arxiv_id"]); stats["arxiv"] += 1

    if sets:
        put("updated_at", "datetime('now')")
        if w.get("metadata_status") in (None, "", "missing"):
            sets.append("metadata_status = 'human_confirmed'")
        params.append(wid)
        conn.execute(f"UPDATE works SET {', '.join(sets)} WHERE id = ?", params)

    if not conn.execute("SELECT COUNT(*) c FROM metadata_extractions WHERE work_id=? AND review_status='approved'", (wid,)).fetchone()["c"]:
        parse = conn.execute("SELECT content_md_path FROM literature_parse_runs WHERE work_id=? AND status='succeeded' AND content_md_path IS NOT NULL AND content_md_path!='' LIMIT 1", (wid,)).fetchone()
        extracted = {k: x for k, x in (("title", v.get("title") or w["title"]),
                                        ("venue", v.get("venue") or w["venue"]),
                                        ("authors", v.get("authors") or json.loads(w["authors"] or "[]")),
                                        ("date", str(v.get("year") or w["year"]))) if x}
        conn.execute(
            "INSERT INTO metadata_extractions (id, work_id, model_name, content_md_path, "
            " input_chars, input_tokens_est, raw_response, extracted_json, confidence_json, "
            " applied, applied_at, created_at, review_status, review_note, reviewed_at, "
            " risk_level, risk_score, risk_reasons, review_source, fix_action) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("ME-" + uuid.uuid4().hex[:12], wid, "human-verified", parse["content_md_path"] if parse else "",
             0, 0, None, json.dumps(extracted, ensure_ascii=False),
             json.dumps({k: "high" for k in extracted}, ensure_ascii=False),
             1, now, now, "approved", (v.get("note") or "") + "；2026-09-02 人读解析稿核实", now,
             "low", 0, "[]", "human", "manual_verify_20260902"))
        stats["rows"] += 1
    conn.commit()

print("统计:", stats, " 处理:", len(V))
conn.close()
