# -*- coding: utf-8 -*-
"""64 条清单内其余文献的元数据回填（2026-09-02，依据：解析稿刊头 + 用户核实清单）。

规则：
- title 仅在当前为文件名式坏标题时覆盖；其余字段仅填空，不覆盖已有值；
- 无 approved 抽取记录的 work 插入 human-verified approved 行（溯源 + 导出门禁）。
"""
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

DB = r"D:\02_academic\doctoral\literature_library\literature.sqlite"

# no: (work_id, title或None=不改, authors或None, year或None, venue或None, doi或None, note)
FIXES = {
 1:  ("W-sha-e2a35f439caf", None, None, None, "International AI Safety Report", None, "隔离状态保持不变；机构署名形式未核实，authors 留空"),
 2:  ("W-sha-f448dfe38f21", None, None, None, "arXiv preprint", None, None),
 3:  ("W-sha-a2c6b17bc301", None, None, None, "arXiv preprint", None, None),
 4:  ("W-arxiv-2603.01608", None, None, 2026, "arXiv preprint", None, None),
 5:  ("W-sha-6bb2ad8fb52a", None, None, None, "NeurIPS 2025 Datasets and Benchmarks Track", None, None),
 6:  ("W-sha-9b9793d6c035", None, None, None, "ICLR 2025", None, None),
 7:  ("W-sha-38f4501d027e", None, None, 2026, "arXiv preprint", None, None),
 8:  ("W-arxiv-2605.06490", None, None, 2026, "arXiv preprint", None, None),
 9:  ("W-arxiv-2607.20121", None, None, 2026, "arXiv preprint", None, None),
 10: ("W-sha-52fd69bfb01d", "An Argument-Based Approach to Validation", ["Michael T. Kane"], 1990, "ACT Research Report ACT-RR-90-13", None, "ERIC ED 336 429；原title 'Kane 1990 Argument Based Validation' 为文件名式坏标题"),
 11: ("W-sha-522eeac8e157", None, ["Department for Science, Innovation and Technology (DSIT)"], 2023, "Command Paper CP 960", None, "原authors被逗号错误切分为3条，已合并修正"),
 13: ("W-sha-74561ba48ca5", None, None, 2018, "Frontiers in Robotics and AI", None, None),
 14: ("W-sha-75f235bb2331", None, None, 2017, "IJCAI 2017", None, None),
 15: ("W-sha-abbf50892706", None, None, 1994, "ETS Research Report RR-94-45", None, None),
 16: ("W-sha-240d509ab76e", "On the Structure of Educational Assessments", ["Robert J. Mislevy", "Linda S. Steinberg", "Russell G. Almond"], 2003, "Measurement", None, "本地PDF为CSE Technical Report 597版（封面仅署Mislevy）；按正式版三人署名回填"),
 17: ("W-sha-4d235aaf17f0", "测验模式效应：来源、检测与应用", ["陈平", "代艺", "黄颖诗"], 2023, "心理科学进展", "10.3724/SP.J.1042.2023.01966", "31(10):1966–1980；原title为Word文件名"),
 19: ("W-sha-b16c4c35fa2c", "Coefficients and Indices in Generalizability Theory", ["Robert L. Brennan"], 2003, "CASMA Research Report No. 1", None, "原title 'ASA.casma.rpt.tex' 为文件名式坏标题"),
 20: ("W-sha-a10e06a26ab6", "ECBD: Evidence-Centered Benchmark Design for NLP", ["Yu Lu Liu", "Su Lin Blodgett", "Jackie Chi Kit Cheung", "Q. Vera Liao", "Alexandra Olteanu", "Ziang Xiao"], 2024, "ACL 2024", None, "16349–16365"),
 21: ("W-sha-b3c5518c5744", None, ["Abigail Z. Jacobs", "Hanna Wallach"], 2021, "FAccT 2021", None, None),
 22: ("W-sha-98d15d259acf", None, None, None, "ACL 2020", None, None),
 23: ("W-sha-342ed9e75f4a", "On the Limits of Minimal Pairs in Contrastive Evaluation", ["Jannis Vamvas", "Rico Sennrich"], 2021, "arXiv preprint", None, "原title为'作者+年份'式坏标题"),
 24: ("W-sha-37bdc95d47fe", None, None, None, "Annals of Statistics", None, None),
 25: ("W-sha-0672782e1bbe", "The Geometry of Generalized Binary Search", ["Robert D. Nowak"], 2011, "IEEE Transactions on Information Theory", None, "57(1)"),
 26: ("W-sha-d563761b1598", "Bayesian Experimental Design: A Review", ["Kathryn Chaloner", "Isabella Verdinelli"], 1995, "Statistical Science", None, "10(3):273–304（JSTOR扫描件首屏）"),
 27: ("W-arxiv-2503.01986", None, None, 2025, "arXiv preprint", None, None),
 28: ("W-arxiv-2605.30322", None, None, 2026, "arXiv preprint", None, None),
 29: ("W-sha-163b484b3b05", "认知诊断计算机化自适应测验的选题策略", ["唐倩", "毛秀珍", "何明霜", "何洁"], 2020, "心理科学进展", "10.3724/SP.J.1042.2020.02160", "28(12):2160–2168；原title为Word文件名"),
 30: ("W-sha-54daf161ef68", "面向大语言模型驱动的智能体的计划复用机制", ["李国鹏", "吴瑞骐", "谈海生", "陈国良"], 2024, "计算机研究与发展", None, "61(11)；原title 'Li 2024 Agent Plan Reuse' 为坏标题"),
 31: ("W-sha-38afe4bbff08", None, None, None, "arXiv preprint", None, None),
 32: ("W-arxiv-2606.10852", None, None, 2026, "arXiv preprint", None, None),
 33: ("W-arxiv-2608.09574", None, None, 2026, "arXiv preprint", None, None),
 34: ("W-sha-77e64bcd8875", None, None, None, "arXiv preprint", None, None),
 35: ("W-arxiv-2605.29729", None, None, 2026, "arXiv preprint", None, None),
 36: ("W-sha-e0dd6416bc58", "JADE-DB：基于靶向变异的大语言模型安全通用基准测试集", ["张谧", "潘旭东", "杨珉"], 2024, "计算机研究与发展", None, "61(5)；原title 'Zhang 2024 JADE DB' 为坏标题"),
 37: ("W-arxiv-2605.05835", None, None, 2026, "arXiv preprint", None, None),
 38: ("W-sha-cc02be84aef7", None, None, 2025, "NeurIPS 2025", None, "NeurIPS 2025 Spotlight"),
 39: ("W-arxiv-2606.23583", None, None, 2026, "arXiv preprint", None, None),
 40: ("W-sha-095a5a7c2516", None, None, 2026, "ICLR 2026 Workshop", None, None),
 41: ("W-sha-3e6cd95a4af7", "On the Social Psychology of the Psychological Experiment: With Particular Reference to Demand Characteristics and Their Implications", ["Martin T. Orne"], 1962, "American Psychologist", None, "17:776–783；解析稿首屏核实；原title 'Orne 1962 Demand Characteristics' 为坏标题"),
 43: ("W-sha-17c16b8de89c", None, None, None, "INLG 2024", None, "230–242"),
 44: ("W-arxiv-2606.08531", None, None, 2026, "arXiv preprint", None, "arXiv改名：清单所记 ForesightSafety-SAGE 现题 VESTA，同一 arXiv ID"),
 45: ("W-arxiv-2607.01793", None, None, 2026, "arXiv preprint", None, None),
 46: ("W-arxiv-2509.20190", None, None, 2025, "arXiv preprint", None, None),
 47: ("W-arxiv-2509.07939", None, None, 2025, "arXiv preprint", None, None),
 48: ("W-arxiv-2607.27294", None, None, 2026, "arXiv preprint", None, None),
 49: ("W-arxiv-2608.06984", None, None, 2026, "arXiv preprint", None, None),
 50: ("W-arxiv-2608.10669", None, None, 2026, "arXiv preprint", None, None),
 51: ("W-arxiv-2608.12996", None, None, 2026, "arXiv preprint", None, None),
 52: ("W-arxiv-2608.09476", None, None, 2026, "arXiv preprint", None, None),
 53: ("W-arxiv-2608.03485", None, None, 2026, "arXiv preprint", None, None),
 54: ("W-arxiv-2608.14940", None, None, 2026, "arXiv preprint", None, None),
 55: ("W-arxiv-2605.10448", None, None, 2026, "arXiv preprint", None, None),
 56: ("W-sha-d15d79a2b2dc", "GPT 系列大语言模型在自然语言处理任务中的鲁棒性", ["陈炫婷", "叶俊杰", "祖璨", "许诺", "桂韬", "张奇"], 2024, "计算机研究与发展", None, "61(5)；原title 'Chen 2024 GPT Robustness' 为坏标题"),
 57: ("W-sha-6d92785328da", "面向大语言模型安全部署的可信评估体系", ["叶文涛", "胡家齐", "王皓波", "陈刚", "赵俊博"], 2025, "计算机研究与发展", None, "62(7)；原title 'Ye 2025 Trustworthy LLM Evaluation' 为坏标题"),
 58: ("W-sha-34a4a0872964", "Can You Trust LLM Judgments? Reliability of LLM-as-a-Judge", ["Kayla Schroeder", "Zach Wood-Doughty"], 2025, "arXiv preprint", None, "原title为'作者+年份'式坏标题；解析稿首屏核实"),
 59: ("W-arxiv-2608.05573", None, None, 2026, "arXiv preprint", None, None),
 61: ("W-sha-3cc743c7aad8", None, ["Drew Keller", "Kweku Kwegyir-Aggrey", "Ryan Steed", "Anita K. Rao", "Julia L. Sharp", "A. Stevie Bergman"], 2026, "NIST AI 800-3", "10.6028/NIST.AI.800-3", "NIST Trustworthy and Responsible AI, February 2026；解析稿首屏核实"),
 64: ("W-sha-55305ebf74c9", None, ["Ravi Dhar", "Itamar Simonson"], 2003, "Journal of Marketing Research", None, "40(2):146–160"),
}

BAD_TITLE_PAT = re.compile(
    r"Microsoft Word|\.tex$|\.pdf$|\.doc$|\.docx$|\.cdr$| et al \d{4}|^\w+ \d{4} |^[A-Z][a-z]+ \d{4} |^[a-z]+ [a-z]+ \d{4}$|^[A-Z]{2,}\.\w+\.")
ZH_BAD_TITLE_PAT = re.compile(r"Microsoft Word|\.cdr$")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc).isoformat(timespec="seconds")
stats = {"title_fixed": 0, "fields_filled": 0, "rows_inserted": 0, "skipped_ok": 0}

for no, (wid, title, authors, year, venue, doi, note) in sorted(FIXES.items()):
    w = dict(conn.execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone())
    if not w:
        print(f"#{no} SKIP {wid}: not found"); continue

    sets, params = [], []
    # title：仅坏标题才覆盖
    if title and BAD_TITLE_PAT.search(w["title"] or ""):
        sets.append("title = ?"); params.append(title)
        if re.search(r"[\u4e00-\u9fff]", title) and not (w.get("title_zh") or "").strip():
            sets.append("title_zh = ?"); params.append(title)
        stats["title_fixed"] += 1
    # authors：空/[]/坏切分才写
    cur_authors = (w.get("authors") or "").strip()
    if authors and (cur_authors in ("", "[]") or wid == "W-sha-522eeac8e157"):
        sets.append("authors = ?"); params.append(json.dumps(authors, ensure_ascii=False))
        stats["fields_filled"] += 1
    for col, val in (("year", year), ("venue", venue), ("doi", doi)):
        if not val:
            continue
        cur = w.get(col)
        if cur is None or not str(cur).strip():
            sets.append(f"{col} = ?"); params.append(val)
            stats["fields_filled"] += 1
    if sets:
        sets.append("updated_at = datetime('now')")
        if w.get("metadata_status") in (None, "", "missing"):
            sets.append("metadata_status = 'human_confirmed'")
        params.append(wid)
        conn.execute(f"UPDATE works SET {', '.join(sets)} WHERE id = ?", params)

    # 无 approved 行的插入 human-verified 行
    has_approved = conn.execute(
        "SELECT COUNT(*) c FROM metadata_extractions WHERE work_id=? AND review_status='approved'", (wid,)).fetchone()["c"]
    if not has_approved:
        parse = conn.execute(
            "SELECT content_md_path FROM literature_parse_runs WHERE work_id=? AND status='succeeded' "
            "AND content_md_path IS NOT NULL AND content_md_path != '' LIMIT 1", (wid,)).fetchone()
        extracted = {k: v for k, v in (("title", title or w["title"]), ("venue", venue or w["venue"]),
                                        ("doi", doi or w["doi"]), ("authors", authors), ("date", str(year or w["year"]))) if v}
        confidence = {k: "high" for k in extracted}
        conn.execute(
            "INSERT INTO metadata_extractions (id, work_id, model_name, content_md_path, "
            " input_chars, input_tokens_est, raw_response, extracted_json, confidence_json, "
            " applied, applied_at, created_at, review_status, review_note, reviewed_at, "
            " risk_level, risk_score, risk_reasons, review_source, fix_action) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("ME-" + uuid.uuid4().hex[:12], wid, "human-verified", parse["content_md_path"] if parse else "",
             0, 0, None, json.dumps(extracted, ensure_ascii=False), json.dumps(confidence, ensure_ascii=False),
             1, now, now, "approved", (note or "") + "；2026-09-02 对照解析稿刊头+用户核实清单回填", now,
             "low", 0, "[]", "human", "backfill_20260902"))
        stats["rows_inserted"] += 1
    conn.commit()
    print(f"#{no:2d} OK {wid}")

conn.close()
print("\n统计:", stats)
