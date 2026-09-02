# -*- coding: utf-8 -*-
"""回填 4 条坏标签 work 的核实元数据（2026-09-02 与用户对照解析稿刊头核实）。

直接更新 works 表 + 插入 approved 的 metadata_extractions 行作溯源
（review_source='human'，review_note 记录核实依据），使导出门禁通过。
"""
import sqlite3
import uuid
from datetime import datetime, timezone

DB = r"D:\02_academic\doctoral\literature_library\literature.sqlite"

FIXES = {
    # 64 条清单 #12：人工智能安全治理框架 2.0
    "W-sha-50735b9ca01b": {
        "title": "人工智能安全治理框架 2.0",
        "title_zh": "人工智能安全治理框架 2.0",
        "authors": ["全国网络安全标准化技术委员会（TC260）",
                     "国家计算机网络应急技术处理协调中心（CNCERT/CC）"],
        "year": 2025,
        "venue": "全国网络安全标准化技术委员会（TC260）",
        "language": "zh",
        "note": "解析稿首屏（works/W-sha-50735b9ca01b/parsed）：TC260+CNCERT 联合发布，2025年9月",
    },
    # 64 条清单 #18：基于游戏的心理测评
    "W-sha-29ffcf0b387a": {
        "title": "基于游戏的心理测评",
        "title_zh": "基于游戏的心理测评",
        "authors": ["徐俊怡", "李中权"],
        "year": 2021,
        "venue": "心理科学进展",
        "doi": "10.3724/SP.J.1042.2021.00394",
        "language": "zh",
        "note": "解析稿首屏：心理科学进展 2021, Vol.29, No.3, 394–403；DOI 见刊头 https://dx.doi.org/10.3724/SP.J.1042.2021.00394；卷期页库表无对应列，暂存于备注（29(3):394–403）",
    },
    # 64 条清单 #42：McCambridge 2012 PLOS ONE
    "W-sha-af2c9c70330d": {
        "title": "The Effects of Demand Characteristics on Research Participant Behaviours in Non-Laboratory Settings: A Systematic Review",
        "authors": ["Jim McCambridge", "Marijn de Bruin", "John Witton"],
        "year": 2012,
        "venue": "PLOS ONE",
        "doi": "10.1371/journal.pone.0039116",
        "note": "解析稿首屏 + 文件名文章号 pone.0039116 互证；卷期 7(6):e39116 库表无对应列，暂存于备注",
    },
    # 64 条清单 #60：Atil 2025 Eval4NLP
    "W-sha-d94638d0e14f": {
        "title": "Non-Determinism of \u201cDeterministic\u201d LLM System Settings in Hosted Environments",
        "authors": ["Berk Atil", "Sarp Aykent", "Alexa Chittams", "Lisheng Fu",
                     "Rebecca J. Passonneau", "Evan Radcliffe", "Guru Rajan Rajagopal",
                     "Adam Sloan", "Tomasz Tudrej", "Ferhan Ture", "Zhe Wu",
                     "Lixinyu Xu", "Breck Baldwin"],
        "year": 2025,
        "venue": "Proceedings of the 5th Workshop on Evaluation and Comparison of NLP Systems (Eval4NLP)",
        "note": "解析稿首屏核实：Eval4NLP-5 @ ACL, December 2025, pages 135–148；页码库表无对应列，暂存于备注。原 title 'Song et al 2025 Nondeterminism Hosted LLMs' 为入库错标",
    },
}

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc).isoformat(timespec="seconds")

for wid, fix in FIXES.items():
    w = conn.execute("SELECT title, language, metadata_status FROM works WHERE id=?", (wid,)).fetchone()
    if not w:
        print(f"SKIP {wid}: not found"); continue
    parse = conn.execute(
        "SELECT content_md_path FROM literature_parse_runs WHERE work_id=? AND status='succeeded' "
        "AND content_md_path IS NOT NULL AND content_md_path != '' LIMIT 1", (wid,)).fetchone()
    md_path = parse["content_md_path"] if parse else ""

    sets, params = ["updated_at = datetime('now')"], []
    for col in ("title", "title_zh", "venue", "doi", "language"):
        if col in fix:
            sets.append(f"{col} = ?"); params.append(fix[col])
    sets.append("authors = ?"); params.append("[" + ", ".join(f'"{a}"' for a in fix["authors"]) + "]")
    sets.append("year = ?"); params.append(fix["year"])
    sets.append("metadata_status = 'human_confirmed'")
    params.append(wid)
    conn.execute(f"UPDATE works SET {', '.join(sets)} WHERE id = ?", params)

    # 该 work 此前无抽取记录；插入 approved 人工核实行作溯源（并让导出门禁通过）
    existing = conn.execute("SELECT COUNT(*) c FROM metadata_extractions WHERE work_id=?", (wid,)).fetchone()["c"]
    if existing == 0:
        extracted = {"title": fix.get("title"), "venue": fix.get("venue"),
                     "doi": fix.get("doi"), "authors": fix["authors"], "date": str(fix["year"])}
        confidence = {k: "high" for k in extracted}
        conn.execute(
            "INSERT INTO metadata_extractions (id, work_id, model_name, content_md_path, "
            " input_chars, input_tokens_est, raw_response, extracted_json, confidence_json, "
            " applied, applied_at, created_at, review_status, review_note, reviewed_at, "
            " risk_level, risk_score, risk_reasons, review_source, fix_action) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("ME-" + uuid.uuid4().hex[:12], wid, "human-verified", md_path,
             0, 0, None,
             __import__("json").dumps(extracted, ensure_ascii=False),
             __import__("json").dumps(confidence, ensure_ascii=False),
             1, now, now, "approved", fix["note"], now,
             "low", 0, "[]", "human", "backfill_20260902"))
    conn.commit()

    after = dict(conn.execute("SELECT id,title,authors,year,venue,doi,metadata_status FROM works WHERE id=?", (wid,)).fetchone())
    print(f"OK {wid}: {after['title'][:60]!r} year={after['year']} status={after['metadata_status']}")

print("\n剩余核对：")
for r in conn.execute("SELECT metadata_status, COUNT(*) c FROM works GROUP BY metadata_status"):
    print(" ", dict(r))
conn.close()
