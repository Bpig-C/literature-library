"""Shared stability rules for metadata, dependencies and bibliography output.

The functions here are deliberately side-effect free.  Submission, review,
usable-basis selection and export all call the same rules so a record cannot
pass one entry and fail another because each path invented its own meaning.
"""
from __future__ import annotations

import json
import re
from typing import Any


MISSING_MARKERS = {
    "", "n/a", "na", "none", "null", "not applicable", "not_applicable",
    "not available", "not_available", "unknown", "未提供", "不适用",
}

# Identity/version changes invalidate a recommendation until a D revision or
# explicit re-review pins the new A.  Scientific-scope fields require review;
# purely presentational/bibliographic changes remain traceable but non-blocking.
METADATA_IDENTITY_FIELDS = {
    "original_title", "authors", "doi", "arxiv", "related_versions",
}
METADATA_SCOPE_FIELDS = {
    "document_type", "publication_status", "date_events", "citation_year",
    "original_abstracts", "resources", "resource_observations",
}


def clean_identifier(value: Any, *, kind: str) -> str | None:
    """Return a real DOI/arXiv value or ``None`` for explicit absence markers."""
    text = str(value or "").strip()
    if text.casefold() in MISSING_MARKERS:
        return None
    if kind == "doi":
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
        text = re.sub(r"^doi:\s*", "", text, flags=re.I).strip()
        return text if text.startswith("10.") and "/" in text else None
    if kind == "arxiv":
        text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text, flags=re.I)
        text = re.sub(r"^arxiv:\s*", "", text, flags=re.I)
        text = re.sub(r"\.pdf$", "", text, flags=re.I).strip()
        return text if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?", text, re.I) else None
    raise ValueError(f"unsupported identifier kind: {kind}")


def _language_matches(candidate: Any, reference: Any) -> bool:
    """Primary-subtag language match ("en" ~ "en-US", "zh" ~ "zh-CN")."""
    left = str(candidate or "").strip().lower().replace("_", "-")
    right = str(reference or "").strip().lower().replace("_", "-")
    if not left or not right:
        return False
    return left.split("-")[0] == right.split("-")[0]


def _entry_bound_version(item: dict) -> str:
    """Normalized paper-version label of an ``original_abstracts`` entry."""
    value = item.get("bound_version")
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip().lower()
    # Existing reviewed records use arXiv:<id>vN and the explicit "fixed PDF"
    # qualifier. Normalize only recognized identifier syntax, not arbitrary
    # prose containing a version number; keep the complete paper identity.
    identifier = clean_identifier(re.sub(r"\s+fixed pdf$", "", text), kind="arxiv")
    if identifier:
        return identifier.lower()
    return text[1:] if re.fullmatch(r"v\d+", text) else text


def catalog_abstract_statement(payload: dict) -> tuple[str | None, str]:
    """Deterministic abstract statement for the catalog row and the active
    bibliographic projection (issues #17 / audit F2-F3).

    Returns ``(text, state)``; ``text`` is only meaningful for
    ``state == "selected"``:

    ``selected``
        entries match the explicitly cited arXiv version, or agree on one
        scope when no version is cited; language is considered afterwards;
    ``version_ambiguous``
        entries conflict or none matches the cited arXiv version; current
        projections must not retain a stale abstract. Source entries remain intact;
    ``explicit_missing``
        ``original_abstracts`` is an explicit empty list: the record addresses
        this version's abstracts and found none — a previously propagated
        value bound to another version must not survive as the current one;
    ``selection_ambiguous``
        several different texts remain after version/language filtering;
        array order cannot decide which is authoritative;
    ``absent``
        the record does not address abstracts at all; callers keep their
        value only if the cited paper identity has not changed, and may fall back to
        the legacy top-level ``abstract`` string read-only.

    Language rule within the confirmed scope (issue #17):
    1. consider only ``original_abstracts`` entries with non-empty text —
       translations and agent overviews never masquerade as the original;
    2. prefer version-labelled entries over unlabelled ones (a label is
       evidence, its absence is not);
    3. prefer the entry matching the formal ``language`` field, then
       ``original_title.language`` (primary-subtag match);
    4. select only a unique text; otherwise leave the selection unconfirmed.
    """
    raw = payload.get("original_abstracts")
    if raw is None:
        legacy = str(payload.get("abstract") or "").strip()
        return (legacy or None, "selected" if legacy else "absent")
    entries = [item for item in raw if isinstance(item, dict)
               and str(item.get("text") or "").strip()]
    if not entries:
        return None, "explicit_missing"
    arxiv = clean_identifier(payload.get("arxiv"), kind="arxiv") or ""
    current = re.search(r"v(\d+)$", arxiv, re.I)
    if current:
        entries = [item for item in entries
                   if _entry_bound_version(item) in {current[1], arxiv.lower()}]
        if not entries:
            return None, "version_ambiguous"
    versions = {_entry_bound_version(item) for item in entries} - {""}
    if current:
        versions = {current[1]}
    if len(versions) > 1:
        return None, "version_ambiguous"
    ordered = [item for item in entries if _entry_bound_version(item)] or entries
    for reference in (payload.get("language"),
                      (payload.get("original_title") or {}).get("language")):
        matching = [item for item in ordered if _language_matches(item.get("language"), reference)]
        if matching:
            ordered = matching
            break
    texts = {str(item["text"]).strip() for item in ordered}
    if len(texts) != 1:
        return None, "selection_ambiguous"
    return next(iter(texts)), "selected"


def select_catalog_abstract(payload: dict) -> str | None:
    """Selected catalog abstract or ``None`` (audit F2: never a guess across
    ambiguous paper versions; explicit-missing and absent states also return
    ``None`` — callers use :func:`catalog_abstract_statement` to tell them
    apart)."""
    text, state = catalog_abstract_statement(payload)
    return text if state == "selected" else None


def official_publication_url(payload: dict) -> str | None:
    """Select an explicitly publication-role URL without inventing one."""
    direct = str(payload.get("url") or "").strip()
    if direct and direct.casefold() not in MISSING_MARKERS:
        return direct
    candidates = list(payload.get("publication_links") or []) + list(payload.get("resources") or [])
    accepted = {
        "official_publication", "publisher", "publication", "paper_homepage",
        "doi_landing", "arxiv_abstract", "publisher_page",
    }
    for item in candidates:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("kind") or "").strip().casefold()
        url = str(item.get("url") or "").strip()
        if role in accepted and url.casefold() not in MISSING_MARKERS and \
                url.lower().startswith(("https://", "http://")):
            return url
    return None


def current_metadata_head(conn, work_id: str, *, approved_stable_only: bool = False):
    """Latest active A version of a work (any review state unless filtered).

    ``approved_stable_only`` selects the newest version that is active AND
    agent-approved AND content-stable — the head a recommendation may build on.
    """
    if approved_stable_only:
        return conn.execute(
            """SELECT * FROM research_metadata_records
               WHERE work_id=? AND validity_status='active'
                 AND agent_review_status='approved' AND content_state='stable'
               ORDER BY version DESC LIMIT 1""", (work_id,)
        ).fetchone()
    return conn.execute(
        """SELECT * FROM research_metadata_records
           WHERE work_id=? AND validity_status='active'
           ORDER BY version DESC LIMIT 1""", (work_id,)
    ).fetchone()


def validate_metadata_pin_for_submission(conn, *, work_id: str,
                                         pinned_record_id: str | None) -> dict:
    """Validate a D-submission's A pin WITHOUT requiring one to exist.

    Layered gate (PLATFORM-004): an *omitted* pin stays a legal v5 submission —
    the record simply cannot be approved or recommended until a revision pins
    a compatible head.  A *provided* pin is checked strictly, because a wrong
    pin must never enter the chain: it must exist, belong to the same work and
    be the work's current active A head (any review state — parallel A/D
    review is legal, ordering is enforced at approval).
    """
    pinned_id = (pinned_record_id or "").strip() or None
    if not pinned_id:
        return {"provided": False, "valid": True}
    pinned = conn.execute(
        "SELECT * FROM research_metadata_records WHERE id=?", (pinned_id,)).fetchone()
    if not pinned:
        raise ValueError(f"metadata_record_id {pinned_id} does not exist")
    if pinned["work_id"] != work_id:
        raise ValueError(
            f"metadata_record_id {pinned_id} belongs to work {pinned['work_id']}, "
            f"not the interpreted work {work_id}")
    if pinned["validity_status"] != "active":
        raise ValueError(
            f"metadata_record_id {pinned_id} is {pinned['validity_status']}; "
            "a new interpretation must pin the current active A head")
    head = current_metadata_head(conn, work_id)
    if not head or head["id"] != pinned_id:
        head_note = f"current head is {head['id']} (v{head['version']})" if head else "no active head"
        raise ValueError(
            f"metadata_record_id {pinned_id} is not the current active A head ({head_note}); "
            "revise the metadata record instead of pinning an old version")
    return {"provided": True, "valid": True, "record_id": pinned_id}


def metadata_change_assessment(old_payload: dict, new_payload: dict) -> dict:
    changed = sorted({*old_payload, *new_payload} - {
        key for key in {*old_payload, *new_payload}
        if old_payload.get(key) == new_payload.get(key)
    })
    identity = sorted(set(changed) & METADATA_IDENTITY_FIELDS)
    scoped = sorted(set(changed) & METADATA_SCOPE_FIELDS)
    if identity:
        level = "blocking"
    elif scoped:
        level = "review_required"
    else:
        level = "non_semantic"
    return {
        "level": level,
        "changed_fields": changed,
        "identity_fields": identity,
        "scope_fields": scoped,
        "requires_rereview": level in {"blocking", "review_required"},
    }


def assess_metadata_dependency(conn, *, work_id: str,
                               pinned_record_id: str | None) -> dict:
    """Assess a D→A pin against the current approved stable A for one work."""
    if not pinned_record_id:
        return {"status": "missing", "usable": False,
                "reason": "D 未固定其消费的 A 元数据记录（source_metadata_record_id 为空）；"
                          "历史记录可读，但推荐基线 fail closed，补正路径是对 D 正式修订并钉定当前 A"}
    pinned = conn.execute(
        "SELECT * FROM research_metadata_records WHERE id=?", (pinned_record_id,)
    ).fetchone()
    if not pinned:
        return {"status": "missing", "usable": False,
                "reason": f"metadata record {pinned_record_id} does not exist"}
    if pinned["work_id"] != work_id:
        return {"status": "identity_conflict", "usable": False,
                "reason": f"metadata record belongs to {pinned['work_id']}, not {work_id}"}
    current = current_metadata_head(conn, work_id, approved_stable_only=True)
    if not current:
        head = current_metadata_head(conn, work_id)
        detail = (f"当前头 {head['id']} 尚未 approved+stable" if head
                  else "该 work 尚无任何 A 记录")
        return {"status": "no_stable_head", "usable": False,
                "pinned_record_id": pinned_record_id,
                "reason": f"work 没有活动且 approved+stable 的 A 头：{detail}"}
    base = {"pinned_record_id": pinned_record_id, "current_record_id": current["id"],
            "pinned_version": pinned["version"], "current_version": current["version"]}
    if current["id"] == pinned_record_id:
        return {**base, "status": "current", "usable": True,
                "impact": {"level": "none", "changed_fields": [], "requires_rereview": False}}
    impact = metadata_change_assessment(
        json.loads(pinned["payload_json"]), json.loads(current["payload_json"]))
    return {**base, "status": "superseded", "usable": not impact["requires_rereview"],
            "impact": impact,
            "reason": ("superseded metadata only changed non-semantic fields" if not impact["requires_rereview"]
                       else "metadata change affects identity or interpretation scope")}
