# -*- coding: utf-8 -*-
"""核对 64 条文献与库内 works 元数据，评估 BibTeX 导出就绪度。"""
import difflib
import json
import re
import sqlite3

DB = r"D:\02_academic\doctoral\literature_library\literature.sqlite"

# (序号, 期望标题, 期望年份, 期望出处列原文, 期望 arXiv id 或 None)
ENTRIES = [
    (1, "International AI Safety Report 2026", 2026, "International AI Safety Report", None),
    (2, "Alignment faking in large language models", 2024, "arXiv preprint", None),
    (3, "PropensityBench: Evaluating Latent Safety Risks", 2025, "arXiv preprint", None),
    (4, "Evaluating and Understanding Scheming Propensity in LLM Agents", 2026, "arXiv:2603.01608", "2603.01608"),
    (5, "DeceptionBench: A Comprehensive Benchmark for AI Deception", 2025, "NeurIPS 2025 D&B Track", None),
    (6, "AI Sandbagging: Language Models Can Strategically Underperform", 2025, "ICLR 2025", None),
    (7, "Decomposing and Measuring Evaluation Awareness", 2026, "arXiv preprint", None),
    (8, "Instrumental Choices: Measuring the Propensity of LLM Agents", 2026, "arXiv:2605.06490", "2605.06490"),
    (9, "OpenSkillRisk: Benchmarking Agent Safety", 2026, "arXiv:2607.20121", "2607.20121"),
    (10, "An Argument-Based Approach to Validation", 1990, "ACT Research Report ACT-RR-90-13", None),
    (11, "Introducing the AI Safety Institute", 2023, "Command Paper CP 960", None),
    (12, "人工智能安全治理框架 2.0", 2025, "2025 年 9 月发布", None),
    (13, "Meaningful Human Control over Autonomous Systems", 2018, "Frontiers in Robotics and AI 5:15", None),
    (14, "The Off-Switch Game", 2017, "IJCAI 2017", None),
    (15, "Validity of Psychological Assessment", 1994, "ETS Research Report RR-94-45", None),
    (16, "On the Structure of Educational Assessments", 2003, "Measurement 1(1)", None),
    (17, "测验模式效应：来源、检测与应用", 2023, "心理科学进展 31(10): 1966–1980", None),
    (18, "基于游戏的心理测评", 2021, "心理科学进展 29(3): 394–403", None),
    (19, "Coefficients and Indices in Generalizability Theory", 2003, "CASMA Research Report No. 1", None),
    (20, "ECBD: Evidence-Centered Benchmark Design for NLP", 2024, "ACL 2024 Long: 16349–16365", None),
    (21, "Measurement and Fairness", 2021, "FAccT '21", None),
    (22, "Beyond Accuracy: Behavioral Testing of NLP Models with CheckList", 2020, "ACL 2020", None),
    (23, "On the Limits of Minimal Pairs in Contrastive Evaluation", 2021, "arXiv preprint", None),
    (24, "Active Sequential Hypothesis Testing", 2013, "Annals of Statistics 41(6)", None),
    (25, "The Geometry of Generalized Binary Search", 2011, "IEEE Trans. IT 57(1)", None),
    (26, "Bayesian Experimental Design: A Review", 1995, "Statistical Science 10(3)", None),
    (27, "Adaptively profiling models with task elicitation", 2025, "arXiv:2503.01986", "2503.01986"),
    (28, "Gram: Assessing sabotage propensities", 2026, "arXiv:2605.30322", "2605.30322"),
    (29, "认知诊断计算机化自适应测验的选题策略", 2020, "心理科学进展 28(12): 2160–2168", None),
    (30, "面向大语言模型驱动的智能体的计划复用机制", 2024, "计算机研究与发展 61(11)", None),
    (31, "The MASK Benchmark: Disentangling Honesty From Accuracy", 2026, "arXiv preprint", None),
    (32, "Janus: A Benchmark for Goal-Conditioned Information Distortion", 2026, "arXiv:2606.10852", "2606.10852"),
    (33, "The Politician, the Liar, and the Obedient Worker", 2026, "arXiv:2608.09574", "2608.09574"),
    (34, "Auditing Games for Sandbagging", 2025, "arXiv preprint", None),
    (35, "Realistic honeypot evaluations for scheming propensity", 2026, "arXiv:2605.29729", "2605.29729"),
    (36, "JADE-DB：基于靶向变异的大语言模型安全通用基准测试集", 2024, "计算机研究与发展 61(5)", None),
    (37, "Evaluation Awareness in Language Models Has Limited Effect", 2026, "arXiv:2605.05835", "2605.05835"),
    (38, "The Hawthorne Effect in Reasoning Models", 2025, "NeurIPS 2025 Spotlight", None),
    (39, "Evaluation Awareness Is Not One Capability", 2026, "arXiv:2606.23583", "2606.23583"),
    (40, "Is Evaluation Awareness Just Format Sensitivity?", 2026, "ICLR 2026 Workshop", None),
    (41, "On the Social Psychology of the Psychological Experiment", 1962, "American Psychologist 17", None),
    (42, "The Effects of Demand Characteristics", 2012, "PLOS ONE 7(6)", None),
    (43, "Is Machine Psychology here?", 2024, "INLG 2024: 230–242", None),
    (44, "ForesightSafety-SAGE: A Fully Automated Scenario Generation", 2026, "arXiv:2606.08531", "2606.08531"),
    (45, "Safety Testing LLM Agents at Scale", 2026, "arXiv:2607.01793", "2607.01793"),
    (46, "STAF: Leveraging LLMs for Automated Attack Tree-Based", 2025, "arXiv:2509.20190", "2509.20190"),
    (47, "Guided Reasoning in LLM-Driven Penetration Testing", 2025, "arXiv:2509.07939", "2509.07939"),
    (48, "AgentS4D: Benchmarking Runtime Risks", 2026, "arXiv:2607.27294", "2607.27294"),
    (49, "HarnessSafe: Evaluating Safety Across Persistent Carriers", 2026, "arXiv:2608.06984", "2608.06984"),
    (50, "REDAgentBench: Executable Red Teaming", 2026, "arXiv:2608.10669", "2608.10669"),
    (51, "ATOBench: Tracing How Autonomous Penetration-Testing Agents", 2026, "arXiv:2608.12996", "2608.12996"),
    (52, "ActBench: Self-Evolving Benchmark of Behavioral Safety", 2026, "arXiv:2608.09476", "2608.09476"),
    (53, "SkillSentry: Adaptive Honey Worlds", 2026, "arXiv:2608.03485", "2608.03485"),
    (54, "When Is an Agent Evaluation Over? Outcome Finality", 2026, "arXiv:2608.14940", "2608.14940"),
    (55, "Can Agent Benchmarks Support Their Scores?", 2026, "arXiv:2605.10448", "2605.10448"),
    (56, "GPT 系列大语言模型在自然语言处理任务中的鲁棒性", 2024, "计算机研究与发展 61(5)", None),
    (57, "面向大语言模型安全部署的可信评估体系", 2025, "计算机研究与发展 62(7)", None),
    (58, "Can You Trust LLM Judgments? Reliability of LLM-as-a-Judge", 2025, "arXiv preprint", None),
    (59, "SkillTV-Bench: Benchmarking How Well Judges Perform", 2026, "arXiv:2608.05573", "2608.05573"),
    (60, 'Non-Determinism of "Deterministic" LLM System Settings', 2025, "Eval4NLP 2025", None),
    (61, "Expanding the AI Evaluation Toolbox with Statistical Models", 2026, "NIST AI 800-3（2026-02）", None),
    (62, "Matching Methods for Causal Inference: A Review and a Look Forward", 2010, "Statistical Science (DOI: 10.1214/09-STS313)", None),
    (63, "The Estimation of Causal Effects by Difference-in-Difference Methods", 2011, "Found. and Trends in Econometrics", None),
    (64, "The Effect of Forced Choice on Choice", 2003, "Journal of Marketing Research 40(2): 146–160", None),
]


def norm(t: str) -> str:
    t = (t or "").lower()
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", t)
    return t


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
works = [dict(r) for r in conn.execute("SELECT * FROM works")]
approved = {
    r["work_id"]
    for r in conn.execute("SELECT DISTINCT work_id FROM metadata_extractions WHERE review_status='approved'")
}

# arXiv id 索引（去连字符、去版本号）
by_arxiv = {}
for w in works:
    aid = (w.get("arxiv_id") or "").strip()
    if aid:
        key = re.sub(r"v\d+$", "", aid.replace("-", ""))
        by_arxiv[key] = w
# 标题索引
by_title = {norm(w.get("title") or ""): w for w in works if norm(w.get("title") or "")}
by_title_zh = {norm(w.get("title_zh") or ""): w for w in works if norm(w.get("title_zh") or "")}

report = []
unmatched = []
for no, etitle, eyear, evenue, earxiv in ENTRIES:
    w = None
    how = ""
    if earxiv:
        w = by_arxiv.get(earxiv.replace("-", ""))
        how = "arxiv_id"
    if w is None:
        key = norm(etitle)
        w = by_title.get(key) or by_title_zh.get(key)
        how = "exact_title"
    if w is None:
        # 模糊：先按年份过滤再取最高相似度
        cands = [x for x in works if x.get("year") == eyear] or works
        best, score = None, 0.0
        for c in cands:
            for t in (c.get("title"), c.get("title_zh")):
                if not t:
                    continue
                s = difflib.SequenceMatcher(None, norm(etitle), norm(t)).ratio()
                if s > score:
                    best, score = c, s
        if score >= 0.60:
            w, how = best, f"fuzzy({score:.2f})"
    if w is None:
        unmatched.append((no, etitle, eyear))
        continue
    report.append({
        "no": no, "match": how,
        "work_id": w["id"],
        "db_title": w.get("title"),
        "db_year": w.get("year"),
        "year_mismatch": (w.get("year") != eyear),
        "authors": w.get("authors"),
        "venue": w.get("venue"),
        "doi": w.get("doi"),
        "arxiv_id": w.get("arxiv_id"),
        "url": w.get("url"),
        "doc_type": w.get("primary_doc_type") or w.get("doc_type"),
        "read_status": w.get("read_status"),
        "metadata_approved": w["id"] in approved,
        "title": bool((w.get("title") or w.get("title_zh") or "").strip()),
        "has_authors": bool((w.get("authors") or "").strip()),
        "has_year": bool(w.get("year")),
        "has_venue": bool((w.get("venue") or "").strip()),
        "has_locator": bool((w.get("doi") or "").strip() or (w.get("arxiv_id") or "").strip() or (w.get("url") or "").strip()),
    })

print(json.dumps({"matched": report, "unmatched": unmatched}, ensure_ascii=False, indent=1))
