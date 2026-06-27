"""Migration decisions for literature_read → literature_library.

Encodes the three human decisions made after Phase 0 inventory review.
Imported by the Phase 2 migration script; not used by inventory.py.
"""

# Decision 1 — Exact-duplicate canonical selection.
#
# Rule: root-level file preferred; if both at same depth, more informative
# filename wins ([Code]_Title or 【R】 format beat bare codes or plain names).
# Exception: DG-sha-0090 where the root file has a misleading/wrong name.
#
# Maps content sha256 → canonical original_name to keep.
# All other files with the same sha256 go to _duplicates/.
CANONICAL_MAP: dict[str, str] = {
    # DG-sha-0017: root 【R】 format beats subfolder [I7] (both structured; root preferred)
    "1152b10cb28865acf923e97de9adb2e9d915dda94fd1950f5bd36ce06188f229":
        "【R】20241218(R,美英AISI)-部署前测试-OpenAI的o1模型.pdf",

    # DG-sha-0031: [I4b] full title beats bare I4b.pdf (no root copy; informativeness wins)
    "33be92efcb58f901d9d2c17e61bf277afbd514a1ac70a642f21e918c21ca25a8":
        "[I4b]_Claude_Opus_4.5_System_Card.pdf",

    # DG-sha-0053: root 【R】arXiv version wins (root + arXiv ID + full title; 3 copies)
    "59f99cd1e80f45f623d31a942ffd25a6312cb6abccc05d92a3f4601b69fb3fce":
        "【R】arXiv-2507.16534(20250726,20250722)-上海AI实验室-实践中的前沿AI风险管理框架_风险分析技术报告(V2).pdf",

    # DG-sha-0067: root 【R】 wins (subfolder has identical-name copy + G2 alias; root preferred)
    "6ed147b66f065722f038c6a933a4b8bb39af9ab2378a72fede629e203c0ab2ae":
        "【R】20251218(R,UK-AISI)-AISI前沿AI趋势报告(EN).pdf",

    # DG-sha-0074: [E11] full title beats bare E11.pdf (no root; informativeness wins)
    "7eaf67dee3b58b308b6fa65d512e59e1b3d6fba9194c483a92267cd9abeef323":
        "[E11]_WMDP_Benchmark.pdf",

    # DG-sha-0090: [I2a] coded name beats root "Frontier Models are Capable.pdf"
    # Root name is a phrase from the abstract, not the paper title; informativeness overrides depth.
    "a8a170a6a268e94c692c2cd28f902001d1ea22441f00f7c63a7f4ee8775f23c6":
        "[I2a]_In-context_Scheming.pdf",

    # DG-sha-0105: [I4g] coded name beats plain "Claude Mythos Preview System Card.pdf" (same depth)
    "c33232e00848eb41f6f1faa3a72578ab887e74ce9e752aca954167e3645ad005":
        "[I4g]_Claude_Mythos_Preview_System_Card.pdf",

    # DG-sha-0111: root 【R】arXiv version wins (root + arXiv ID beats subfolder [E18])
    "cc5eb177ee5c137c0fc14381908f4472e4006c484fcbbf34c67e4eb607d732bd":
        "【R】arXiv-2512.01166(20260430,20251201)-SaferAI-测评AI提供商的前沿安全框架(V5).pdf",

    # DG-sha-0117: [E1] full title beats bare E1.pdf (no root; informativeness wins)
    "d313da7474acbf06f42d5f61ed5d18c9d9d199d60673e173e157cce18e819389":
        "[E1]_Measuring_AI_Ability_Long_Tasks.pdf",
}


# Decision 2 — I4j code disambiguation.
#
# Two PDFs share code I4j; they are on the same research line:
#   - [I4j]_Agentic_Misalignment_Appendix.pdf  → technical testbed/appendix (I4j-a)
#   - [I4j]_Alignment_Evaluation_OpenAI_Findings.pdf → joint eval summary (I4j, primary)
# The second paper cites the first's testbed as a component in its
# "Hand-Built Agentic Misalignment Testbeds" section.
# WorkRelation: I4j-a part_of I4j.
#
# Decision 3 — X2 code disambiguation.
#
# Three different Grok model cards share bare code X2; split into X2a/b/c.
#
# Maps original_name → {code, optional relation}.
CODE_OVERRIDES: dict[str, dict] = {
    "[I4j]_Agentic_Misalignment_Appendix.pdf": {
        "code": "I4j-a",
        "relation": {
            "type": "part_of",
            "target_original_name": "[I4j]_Alignment_Evaluation_OpenAI_Findings.pdf",
        },
    },
    "[I4j]_Alignment_Evaluation_OpenAI_Findings.pdf": {
        "code": "I4j",
    },
    "X2_Grok_4_Fast_Model_Card.pdf":      {"code": "X2a"},
    "X2_Grok_4_Model_Card.pdf":            {"code": "X2b"},
    "X2_Grok_Code_Fast_1_Model_Card.pdf":  {"code": "X2c"},
}


# MD template extracts will not be migrated to the new library.
# Low-quality data; full-text MinerU parsing will replace them.
SKIP_TEMPLATE_EXTRACTS: bool = True
