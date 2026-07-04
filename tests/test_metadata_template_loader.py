"""Tests for metadata template runtime integration."""

from __future__ import annotations

import json


def _use_tmp_templates(monkeypatch, tmp_path, metadata):
    from api import metadata_template as mt

    monkeypatch.setattr(mt, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(mt, "TEMPLATES_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(mt, "BACKUPS_DIR", tmp_path / "backups")
    (tmp_path / "templates.json").write_text(
        json.dumps({"metadata": metadata}, ensure_ascii=False),
        encoding="utf-8",
    )
    return mt


def test_custom_metadata_field_enters_prompt(monkeypatch, tmp_path):
    mt = _use_tmp_templates(
        monkeypatch,
        tmp_path,
        {
            "version": "2.0-test",
            "fields": [
                *mt_fields_without_custom(),
                {
                    "key": "journal",
                    "label": "期刊",
                    "type": "text",
                    "rules": "journal name or null",
                    "description": "Publication journal when explicitly stated",
                },
            ],
        },
    )

    template = mt.get_metadata_template()
    prompt = mt.build_metadata_user_prompt("Document text", template)

    assert "Template version: 2.0-test" in prompt
    assert "journal (期刊, text)" in prompt
    assert '"journal"' in prompt


def test_validate_extraction_missing_uses_active_template(monkeypatch, tmp_path):
    mt = _use_tmp_templates(
        monkeypatch,
        tmp_path,
        {
            "version": "2.0-test",
            "fields": [
                *mt_fields_without_custom(),
                {
                    "key": "journal",
                    "label": "期刊",
                    "type": "text",
                    "rules": "journal name or null",
                    "description": "Publication journal when explicitly stated",
                },
            ],
        },
    )
    from scripts.literature_metadata_extract import validate_extraction

    data, warnings = validate_extraction({
        "title": "T",
        "authors": [],
        "contributors": [],
        "confidence": {},
    })

    assert "journal" in data["missing"]
    assert "publication_date" in data["missing"]
    assert isinstance(warnings, list)


def test_prompt_template_legacy_format_remains_usable():
    from api.metadata_template import USER_PROMPT_TEMPLATE

    rendered = USER_PROMPT_TEMPLATE.format(text="Document body")

    assert "Document body" in rendered
    assert '"title"' in rendered


def test_rerun_field_aliases_normalize_to_canonical():
    from api.metadata_template import normalize_metadata_fields, valid_rerun_fields

    assert "date" in valid_rerun_fields()
    assert "institutions" in valid_rerun_fields()
    assert normalize_metadata_fields(["date", "institutions", "title"]) == [
        "publication_date",
        "contributors",
        "title",
    ]


def mt_fields_without_custom():
    from api.metadata_template import BUILTIN_METADATA_FIELDS

    return [dict(field) for field in BUILTIN_METADATA_FIELDS]
