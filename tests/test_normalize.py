# tests/test_normalize.py
from collector import normalize as N

def test_normalize_arxiv_strips_version():
    assert N.normalize_arxiv_id("2406.10162v3") == "2406.10162"
    assert N.normalize_arxiv_id("arxiv:2406.10162") == "2406.10162"
    assert N.normalize_arxiv_id("not-an-id") is None

def test_normalize_doi():
    assert N.normalize_doi("https://doi.org/10.1000/xyz") == "10.1000/xyz"
    assert N.normalize_doi("10.1000/xyz") == "10.1000/xyz"

def test_normalize_github_url():
    assert N.normalize_github_url("https://github.com/org/repo/") == "org/repo"
    assert N.normalize_github_url("https://github.com/org/repo.git") == "org/repo"
    assert N.normalize_github_url("not github") is None
