"""Unit tests for api/export_format.py（纯函数，无需 DB）。"""

from __future__ import annotations

from api.export_format import (
    MATRIX_COLUMNS,
    parse_authors,
    work_to_bibtex,
    work_to_ris,
    works_to_matrix_csv,
)


def _work(**over):
    base = {
        "id": "W-test-001",
        "title": "A Study of 100% Coverage & Beyond",
        "title_zh": "覆盖率研究",
        "authors": '["Alice Smith", "Bob 李", "Carol Jones"]',
        "year": 2025,
        "doi": "10.1234/test",
        "arxiv_id": "2501.00001",
        "venue": "NeurIPS",
        "url": "https://example.org/paper",
        "abstract": "We study things.",
        "primary_doc_type": "research_article",
        "doc_type": "paper",
        "language": "en",
    }
    base.update(over)
    return base


# ---------- parse_authors ----------

def test_parse_authors_json_array():
    assert parse_authors('["A", "B", "C"]') == ["A", "B", "C"]


def test_parse_authors_plain_string_fallback():
    assert parse_authors("Alice Smith; Bob Lee") == ["Alice Smith", "Bob Lee"]
    assert parse_authors("Alice Smith") == ["Alice Smith"]


def test_parse_authors_empty_and_broken():
    assert parse_authors(None) == []
    assert parse_authors("") == []
    assert parse_authors("[broken json") == ["[broken json"]


# ---------- BibTeX ----------

def test_bibtex_article_full_fields():
    out = work_to_bibtex(_work())
    assert out.startswith("@article{W-test-001,")
    assert "author = {Alice Smith and Bob 李 and Carol Jones}" in out
    assert "journal = {NeurIPS}" in out
    assert "doi = {10.1234/test}" in out
    assert "eprint = {2501.00001}" in out
    assert "archiveprefix = {arXiv}" in out
    assert "year = {2025}" in out


def test_bibtex_type_mapping():
    assert work_to_bibtex(_work(primary_doc_type="system_model_card")).startswith("@techreport{")
    assert work_to_bibtex(_work(primary_doc_type="survey_review")).startswith("@article{")
    assert work_to_bibtex(_work(primary_doc_type="webpage_blog")).startswith("@misc{")
    assert work_to_bibtex(_work(primary_doc_type=None, doc_type=None)).startswith("@misc{")


def test_bibtex_inproceedings_uses_booktitle():
    out = work_to_bibtex(_work(primary_doc_type="benchmark_dataset_paper"))
    assert out.startswith("@inproceedings{")
    assert "booktitle = {NeurIPS}" in out


def test_bibtex_missing_fields_omitted():
    out = work_to_bibtex(_work(doi=None, arxiv_id=None, url=None, venue=None, abstract=None))
    assert "doi = {" not in out
    assert "eprint = {" not in out
    assert "url = {" not in out
    assert "journal = {" not in out


def test_bibtex_escapes_special_chars():
    out = work_to_bibtex(_work())
    assert r"100\% Coverage \& Beyond" in out
    assert out.count("{{") >= 1  # title 大小写保护


def test_bibtex_escapes_structure_and_math_chars():
    out = work_to_bibtex(_work(title="Braces {x} and $math$ and a_b ^ caret ~ tilde"))
    assert r"\{x\}" in out
    assert r"\$math\$" in out
    assert r"a\_b" in out
    assert "textasciicircum" in out
    assert "textasciitilde" in out


def test_bibtex_thesis_and_chapter_mapping():
    assert work_to_bibtex(_work(primary_doc_type="thesis")).startswith("@phdthesis{")
    out = work_to_bibtex(_work(primary_doc_type="book_chapter"))
    assert out.startswith("@incollection{")
    assert "booktitle = {NeurIPS}" in out


def test_bibtex_title_fallback_title_zh():
    out = work_to_bibtex(_work(title=None))
    assert "覆盖率研究" in out


# ---------- RIS ----------

def test_ris_basic():
    out = work_to_ris(_work(), {"method_tags": ["red_teaming", "benchmark_construction"]})
    lines = out.splitlines()
    assert lines[0] == "TY  - JOUR"
    assert lines.count("AU  - Alice Smith") == 1
    assert "AU  - Bob 李" in lines
    assert "JO  - NeurIPS" in lines
    assert "DO  - 10.1234/test" in lines
    assert "KW  - red_teaming" in lines
    assert "KW  - benchmark_construction" in lines
    assert "ID  - W-test-001" in lines
    assert lines[-1] == "ER  - "


def test_ris_type_mapping():
    assert work_to_ris(_work(primary_doc_type="benchmark_dataset_paper")).startswith("TY  - CONF")
    assert work_to_ris(_work(primary_doc_type="system_model_card")).startswith("TY  - RPRT")
    assert work_to_ris(_work(primary_doc_type="webpage_blog")).startswith("TY  - GEN")
    assert work_to_ris(_work(primary_doc_type="thesis")).startswith("TY  - THES")
    assert work_to_ris(_work(primary_doc_type="book_chapter")).startswith("TY  - CHAP")


def test_ris_includes_arxiv_eprint():
    out = work_to_ris(_work())
    assert "EP  - 2501.00001" in out.splitlines()


def test_ris_missing_fields_omitted():
    out = work_to_ris(_work(venue=None, doi=None, url=None, abstract=None))
    assert "JO  - " not in out
    assert "DO  - " not in out
    assert "UR  - " not in out
    assert "AB  - " not in out


# ---------- 综述矩阵 CSV ----------

def test_matrix_csv_columns_and_bom():
    rows = [
        dict(_work(), tags={"method_tags": ["a", "b"], "risk_domain": ["deception"], "artifact_focus": ["benchmark"]},
             priority="high", is_core_literature=1, one_sentence_positioning="定位句"),
        dict(_work(id="W-test-002", title="No Digest", primary_doc_type=None),
             tags={}, priority=None, is_core_literature=0, one_sentence_positioning=""),
    ]
    out = works_to_matrix_csv(rows)
    assert out.startswith("\ufeff")
    header = out.splitlines()[0].lstrip("\ufeff")
    assert header == ",".join(MATRIX_COLUMNS)
    assert "a; b" in out
    assert "定位句" in out
    assert "是" in out
    # 第二行 digest 留空、核心文献留空
    line2 = out.splitlines()[2]
    assert line2.endswith(",")
    assert "No Digest" in line2


def test_matrix_csv_quoting_with_comma_and_newline():
    rows = [dict(_work(title='Has, comma and "quote"', abstract="line1\nline2"), tags={}, one_sentence_positioning="")]
    out = works_to_matrix_csv(rows)
    assert '"Has, comma and ""quote"""' in out
    parsed = list(__import__("csv").reader(out.lstrip("\ufeff").splitlines()))
    assert parsed[1][1] == 'Has, comma and "quote"'


def test_matrix_csv_formula_injection_guard():
    rows = [dict(_work(id="=HYPERLINK(x)", title="+cmd"), tags={}, one_sentence_positioning="")]
    out = works_to_matrix_csv(rows)
    line = out.splitlines()[1]
    assert line.startswith("'=HYPERLINK(x),'+cmd,")
