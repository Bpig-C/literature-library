"""Shared application service for external-agent literature research.

FastAPI and CLI are adapters over this module.  It never reads legacy
``analysis_runs`` and never writes legacy ``works``/``source_files``.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .research_context import ResearchContext
from .research_schema import CONTRACT, compute_environment_id, verify_schema
from .research_definitions import (DefinitionService, derive_association_summaries,
                                   released_vocabularies_for, validate_associations,
                                   validate_locator, validate_payload_against_definition)
from .research_operations import record_operation_effect
from .research_stability import (assess_metadata_dependency, current_metadata_head,
                                 validate_metadata_pin_for_submission)


STATUSES = CONTRACT["statuses"]


def _require_environment(context: ResearchContext, environment_id: str | None) -> str:
    """Every write binds the research environment it claims to operate on."""
    expected = compute_environment_id(context.library_root, context.db_path)
    if not environment_id or not str(environment_id).strip():
        raise ValueError(
            f"submission must bind the research environment: pass environment_id={expected} "
            "(published in the task package)")
    if str(environment_id).strip() != expected:
        raise ValueError(
            f"environment_id mismatch: submission claims {environment_id} but this research "
            f"environment is {expected}; refuses to write into a cloned/moved store")
    return expected


class ResearchConflictError(ValueError):
    """A stable identity key was reused for a different immutable intent."""


def _resolve_release_binding(context: ResearchContext, release_id: str | None,
                             layers: list[str]) -> tuple[str, str]:
    """Bind a submission to an immutable release bundle (contract v5).

    Contract v5: every new write binds a release bundle — the explicitly given
    one, or the latest released bundle.  There is deliberately no unbound path
    left: legacy records exist only as migrated data marked needs_completion,
    never as new unvalidated writes.
    """
    refs = DefinitionService(context).resolve_release(release_id)
    available = {ref["layer"] for ref in refs["definition_refs"]}
    missing = [layer for layer in layers if layer not in available]
    if missing:
        raise ValueError(f"release {refs['id']} has no definition for layers: {missing}")
    return refs["id"], json.dumps(refs["definition_refs"], ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def _row_value(row: sqlite3.Row, key: str, default: str | None = None) -> str | None:
    """v4-safe column read: pre-conversion stores lack content_state etc."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _c(v5: bool, expr: str) -> str:
    """Column expression when the v5 lifecycle columns exist, else literal NULL."""
    return expr if v5 else "NULL"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def research_v5_available(conn: sqlite3.Connection) -> bool:
    """True when the store has the v5 content-lifecycle columns (post-conversion)."""
    return "content_state" in _table_columns(conn, "research_interpretations") and \
        "content_state" in _table_columns(conn, "research_source_records")


def _source_lineage_edges(conn: sqlite3.Connection, head_id: str,
                          ancestor_id: str) -> list[tuple[str, str]] | None:
    """Return ``(prior, new)`` edges from ancestor to head, or ``None``.

    Interpretations deliberately remain pinned to the C record they actually
    interpreted.  Consumption may nevertheless carry that D forward when the
    current C head is a proven direct descendant and every intervening change
    was classified for that D.  Walking ``supersedes_id`` avoids rebinding D
    and prevents a record on a sibling branch from being mistaken for an
    ancestor.
    """
    if head_id == ancestor_id:
        return []
    reverse_edges: list[tuple[str, str]] = []
    seen: set[str] = set()
    current = head_id
    while current and current not in seen:
        seen.add(current)
        row = conn.execute(
            "SELECT supersedes_id FROM research_source_records WHERE id=?",
            (current,)).fetchone()
        if not row or not row["supersedes_id"]:
            return None
        prior = row["supersedes_id"]
        reverse_edges.append((prior, current))
        if prior == ancestor_id:
            return list(reversed(reverse_edges))
        current = prior
    return None


def _compatible_interpretation(conn: sqlite3.Connection, *, batch_id: str,
                               source_id: str, head_id: str,
                               v5: bool) -> tuple[dict | None, list[dict]]:
    """Resolve the newest stable D compatible with the current stable C head.

    Compatibility is conservative: a descendant edge without a persisted
    impact decision is not inferred safe.  Locator-only decisions preserve
    usability while remaining visible as pending dependency review; semantic
    decisions block carry-forward (normally the review transition has already
    marked D stale).  All lineage edges are checked so a later unrelated
    revision cannot wash an earlier impact clean.
    """
    stable = "AND content_state='stable'" if v5 else ""
    candidates = conn.execute(
        f"""SELECT * FROM research_interpretations
            WHERE batch_id=? AND source_id=? AND validity_status='active'
              AND validation_status='passed' AND agent_review_status='approved'
              {stable}
            ORDER BY version DESC, id DESC""", (batch_id, source_id)).fetchall()
    has_impacts = v5 and conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_source_impacts'"
    ).fetchone() is not None
    resolved: list[tuple[int, int, str, dict, list[dict]]] = []
    for candidate in candidates:
        edges = _source_lineage_edges(conn, head_id, candidate["source_record_id"])
        if edges is None:
            continue
        pending: list[dict] = []
        compatible = True
        for prior_id, new_id in edges:
            if not has_impacts:
                compatible = False
                break
            impact = conn.execute(
                """SELECT impacted_unit_keys_json,change_kind,requires_rereview
                   FROM research_source_impacts
                   WHERE prior_source_record_id=? AND new_source_record_id=?
                     AND interpretation_id=?""",
                (prior_id, new_id, candidate["id"])).fetchone()
            if not impact or impact["change_kind"] == "semantic":
                compatible = False
                break
            if impact["requires_rereview"]:
                pending.append({
                    "prior_source_record_id": prior_id,
                    "source_record_id": new_id,
                    "impacted_unit_keys": json.loads(
                        impact["impacted_unit_keys_json"] or "[]"),
                    "change_kind": impact["change_kind"],
                })
        if compatible:
            # Prefer a D bound closest to the current C head.  Interpretation
            # versions are scoped to their bound C, so version alone cannot
            # rank an ancestor D against a newly reviewed current-head D.
            resolved.append((len(edges), -int(candidate["version"]),
                             str(candidate["id"]), dict(candidate), pending))
    if resolved:
        _, _, _, candidate, pending = min(resolved, key=lambda value: value[:3])
        return candidate, pending
    return None, []


def _public_source(row: sqlite3.Row | dict) -> dict:
    """Return stable source identity without legacy source-level parse state."""
    value = dict(row)
    for key in ("parse_run_id", "parse_exists", "parse_quality"):
        value.pop(key, None)
    return value


def _record_submitter(conn: sqlite3.Connection, batch_id: str | None,
                      source_id: str | None) -> str | None:
    """Legacy lookup kept for diagnostics only.

    Reviewer independence (B2) must NOT use this: the batch item's claim
    holder changes with every re-claim, so a submitter derived here would
    let the original worker approve their own record after another worker
    claimed the item.  Records pin ``submitted_by`` at submit time; review
    gates read that column.
    """
    if not batch_id or not source_id:
        return None
    row = conn.execute(
        "SELECT worker_owner FROM research_batch_items WHERE batch_id=? AND source_id=?",
        (batch_id, source_id)).fetchone()
    if row and row["worker_owner"]:
        return row["worker_owner"]
    row = conn.execute(
        """SELECT e.worker_owner FROM research_batch_item_events e
           JOIN research_batch_items bi ON bi.id=e.item_id
           WHERE bi.batch_id=? AND bi.source_id=? AND e.worker_owner IS NOT NULL
           ORDER BY e.rowid DESC LIMIT 1""",
        (batch_id, source_id)).fetchone()
    return row["worker_owner"] if row else None


def _require_reviewer_identity(decision: str, actor_id: str | None,
                               submitted_by: str | None = None, *,
                               action: str) -> None:
    """工单要求：真实核查/运行身份必须落库。

    使记录进入 stable/adopted 的决定必须携带非空 actor_id（已识别的核查
    者），且不得与该记录提交者相同——空身份永远到不了 stable，提交者
    自审也不能冒充独立核查。
    """
    if actor_id is None or not str(actor_id).strip():
        raise ValueError(
            f"{action}: {decision} requires a non-empty actor_id "
            "(an identified reviewer is recorded with the review event)")
    if submitted_by and str(actor_id).strip() == str(submitted_by).strip():
        raise ValueError(
            f"{action}: submitter {submitted_by} cannot act as the independent reviewer")


def _check_explicit_release_change(conn: sqlite3.Connection, batch_id: str,
                                   bound_release_id: str, manual_action: bool,
                                   manual_reason: str | None, layer_label: str) -> None:
    """B5(R6): submitting under a release OTHER than the batch's pinned one is
    an intentional, auditable change — allowed only as an explicit manual act
    with a stated reason; a plain worker submission silently pairing another
    bundle with the batch's task is a conflict."""
    batch_row = conn.execute(
        "SELECT release_id FROM research_batches WHERE id=?", (batch_id,)).fetchone()
    batch_pin = batch_row["release_id"] if batch_row and "release_id" in batch_row.keys() else None
    if batch_pin and bound_release_id != batch_pin:
        if not (manual_action and (manual_reason or "").strip()):
            raise ValueError(
                f"batch {batch_id} is pinned to release {batch_pin}; this {layer_label} "
                f"submission binds {bound_release_id}. Changing the task's release "
                "requires an explicit manual change with a stated reason "
                "(manual_action + manual_reason), not a silent re-binding")


def _normalize_targets(targets: dict | None) -> dict | None:
    """B6: normalize the plan's scope contract into a machine-checkable form.

    The free-form dict the API accepts is checked here so downstream
    completion/usability logic can rely on fixed semantics instead of
    guessing arbitrary strings: layer levels are "required"/"not_applicable",
    scope carries unit_keys, per_source narrows per source id.
    """
    if targets is None:
        return None
    if not isinstance(targets, dict):
        raise ValueError("targets must be an object")
    normalized: dict = {}
    allowed_top = {"source_record", "interpretation", "scope", "per_source"}
    unknown = sorted(set(targets) - allowed_top)
    if unknown:
        raise ValueError(f"targets has unknown keys: {unknown} (allowed: {sorted(allowed_top)})")

    def _level(key: str, value) -> str:
        value = str(value or "").strip()
        if value and value not in {"required", "not_applicable"}:
            raise ValueError(
                f"targets.{key} must be 'required' or 'not_applicable' (got '{value}')")
        return value

    for key in ("source_record", "interpretation"):
        level = _level(key, targets.get(key))
        if level:
            normalized[key] = level
    scope = targets.get("scope")
    if scope is not None:
        if not isinstance(scope, dict):
            raise ValueError("targets.scope must be an object")
        unit_keys = scope.get("unit_keys")
        if unit_keys is not None:
            if not isinstance(unit_keys, list) or \
                    not all(isinstance(k, str) and k.strip() for k in unit_keys):
                raise ValueError("targets.scope.unit_keys must be a list of unit keys")
            normalized["scope"] = {"unit_keys": sorted(set(unit_keys))}
        unknown_scope = sorted(set(scope) - {"unit_keys"})
        if unknown_scope:
            raise ValueError(f"targets.scope has unknown keys: {unknown_scope}")
    per_source = targets.get("per_source")
    if per_source is not None:
        if not isinstance(per_source, dict) or not per_source:
            raise ValueError("targets.per_source must be a non-empty object keyed by source_id")
        normalized_per: dict = {}
        for source_id, entry in per_source.items():
            if not isinstance(entry, dict):
                raise ValueError(f"targets.per_source[{source_id}] must be an object")
            entry_norm: dict = {}
            for key in ("source_record", "interpretation"):
                level = _level(key, entry.get(key))
                if level:
                    entry_norm[key] = level
            entry_scope = entry.get("scope")
            if entry_scope is not None:
                if not isinstance(entry_scope, dict) or \
                        not isinstance(entry_scope.get("unit_keys"), list):
                    raise ValueError(
                        f"targets.per_source[{source_id}].scope.unit_keys must be a list")
                entry_norm["scope"] = {"unit_keys": sorted(set(entry_scope["unit_keys"]))}
            unknown_entry = sorted(set(entry) - {"source_record", "interpretation", "scope"})
            if unknown_entry:
                raise ValueError(
                    f"targets.per_source[{source_id}] has unknown keys: {unknown_entry}")
            normalized_per[str(source_id)] = entry_norm
        normalized["per_source"] = normalized_per
    return normalized or None


def _requested_scope_targets(conn: sqlite3.Connection, batch_id: str,
                             source_id: str | None = None) -> dict | None:
    """The batch's normalized plan targets, or None when nothing was planned."""
    try:
        row = conn.execute("SELECT plan_targets_json FROM research_batches WHERE id=?",
                           (batch_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or not row["plan_targets_json"]:
        return None
    try:
        targets = json.loads(row["plan_targets_json"])
    except (TypeError, ValueError):
        return None
    if not isinstance(targets, dict):
        return None
    if source_id and isinstance(targets.get("per_source"), dict) and \
            isinstance(targets["per_source"].get(source_id), dict):
        merged = {k: v for k, v in targets.items() if k != "per_source"}
        # B6(R6): per_source MERGES over the global declaration, so the
        # explicit write and the inherited write are the same contract.
        merged.update(targets["per_source"][source_id])
        return merged
    return targets


def _interpretation_not_required(conn: sqlite3.Connection, batch_id: str,
                                 source_id: str, source_record) -> bool:
    """B6: the request target determines whether the D layer is required.

    An explicitly requested interpretation (``targets.interpretation ==
    'required'``) wins over the record's own ``record_mode`` — a delegated
    task contract cannot be silently overridden by submitting a background C.
    Otherwise an interpretation is not required when the plan marks it
    not_applicable (globally or per source), or when the bound source record
    declares ``record_mode`` background/not_applicable.  "not planned" is
    never silently reinterpreted as "not needed".
    """
    targets = _requested_scope_targets(conn, batch_id, source_id)
    if targets:
        level = str(targets.get("interpretation") or "").strip()
        if level == "required":
            return False
        if level == "not_applicable":
            return True
    if source_record is not None:
        try:
            payload = json.loads(source_record["payload_json"])
        except (TypeError, ValueError):
            return False
        if str(payload.get("record_mode") or "units") in {"background", "not_applicable"}:
            return True
    return False


def _concept_ids(payload: dict) -> set[str]:
    concepts = payload.get("concepts") if isinstance(payload, dict) else None
    if not isinstance(concepts, list):
        raise ValueError("ontology payload must contain a concepts list")
    ids = set()
    for concept in concepts:
        if not isinstance(concept, dict) or not (concept.get("id") or concept.get("key")):
            raise ValueError("every ontology concept requires an id")
        ids.add(str(concept.get("id") or concept.get("key")))
    return ids


def _canonical_claims(claims: list[dict]) -> str:
    """Normalize submission/existing claim shapes for idempotency checks."""
    normalized = []
    for claim in claims:
        evidence = []
        for item in claim.get("evidence") or []:
            quote = str(item.get("quote", ""))
            start = item.get("start_offset")
            end = item.get("end_offset")
            if start is not None and end is None:
                end = start + len(quote)
            evidence.append({
                "quote": quote,
                "start_offset": start,
                "end_offset": end,
                "locator": item.get("locator") or {},
            })
        normalized.append({
            "key": str(claim.get("key", "")),
            "text": str(claim.get("text", "")),
            "evidence": sorted(evidence, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)),
        })
    normalized.sort(key=lambda value: (value["key"], value["text"]))
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _unit_for_claim(claim_key: str, unit_keys: set[str]) -> str | None:
    """Resolve the lightweight claim→unit convention used by the v5 contract.

    Exact unit keys are preferred; ``u1-claim``/``u1.claim`` style keys are
    accepted for existing content.  Ambiguous or unscoped keys stay unknown so
    callers conservatively re-review instead of guessing a dependency.
    """
    key = str(claim_key or "")
    matches = [unit for unit in unit_keys if key == unit or any(
        key.startswith(unit + separator) for separator in ("-", "_", ".", ":"))]
    return matches[0] if len(matches) == 1 else None


def _source_revision_changes(conn: sqlite3.Connection, old_id: str,
                             new_id: str) -> tuple[set[str], set[str], bool]:
    """Return semantic units, locator-only units and unknown semantic change.

    Unlike the former payload-only comparison this reads normalized claim and
    evidence rows as well as named extensions.  Unknown scope is deliberately
    conservative; it affects every dependent interpretation.
    """
    old_row = conn.execute("SELECT payload_json FROM research_source_records WHERE id=?",
                           (old_id,)).fetchone()
    new_row = conn.execute("SELECT payload_json FROM research_source_records WHERE id=?",
                           (new_id,)).fetchone()
    if not old_row or not new_row:
        return set(), set(), True
    old_payload, new_payload = json.loads(old_row[0]), json.loads(new_row[0])
    old_units = {str(u.get("unit_key")): u for u in old_payload.get("units") or []
                 if isinstance(u, dict) and u.get("unit_key")}
    new_units = {str(u.get("unit_key")): u for u in new_payload.get("units") or []
                 if isinstance(u, dict) and u.get("unit_key")}
    unit_keys = set(old_units) | set(new_units)
    semantic = {key for key in unit_keys if old_units.get(key) != new_units.get(key)}
    locator_only: set[str] = set()
    unknown_semantic = False

    def base(payload: dict) -> dict:
        return {k: v for k, v in payload.items() if k not in {"units", "extensions"}}
    if base(old_payload) != base(new_payload):
        unknown_semantic = True

    def scoped_extensions(payload: dict) -> tuple[dict[str, list], list]:
        by_unit = {key: [] for key in unit_keys}
        unknown = []
        for extension in payload.get("extensions") or []:
            if not isinstance(extension, dict):
                unknown.append(extension); continue
            raw_scope = extension.get("scope")
            scopes = raw_scope if isinstance(raw_scope, list) else [raw_scope]
            matched = False
            for scope in scopes:
                if str(scope) in by_unit:
                    by_unit[str(scope)].append(extension); matched = True
            if not matched:
                unknown.append(extension)
        return by_unit, unknown
    old_ext, old_unknown_ext = scoped_extensions(old_payload)
    new_ext, new_unknown_ext = scoped_extensions(new_payload)
    semantic |= {key for key in unit_keys if old_ext[key] != new_ext[key]}
    if old_unknown_ext != new_unknown_ext:
        unknown_semantic = True

    def claims(record_id: str) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for claim in conn.execute(
                "SELECT id,claim_key,claim_text FROM research_claims "
                "WHERE record_layer='source_record' AND record_id=?", (record_id,)):
            evidence = []
            for ev in conn.execute(
                    "SELECT quote,start_offset,end_offset,locator_json FROM research_evidence "
                    "WHERE claim_id=? ORDER BY start_offset,id", (claim["id"],)):
                evidence.append({"quote": ev["quote"], "start_offset": ev["start_offset"],
                                 "end_offset": ev["end_offset"],
                                 "locator": json.loads(ev["locator_json"] or "{}")})
            result[claim["claim_key"]] = {"text": claim["claim_text"], "evidence": evidence}
        return result
    old_claims, new_claims = claims(old_id), claims(new_id)
    for claim_key in set(old_claims) | set(new_claims):
        before, after = old_claims.get(claim_key), new_claims.get(claim_key)
        unit = _unit_for_claim(claim_key, unit_keys)
        if before is None or after is None:
            if unit: semantic.add(unit)
            else: unknown_semantic = True
            continue
        before_sem = {"text": before["text"], "evidence": [
            {k: v for k, v in ev.items() if k != "locator"} for ev in before["evidence"]]}
        after_sem = {"text": after["text"], "evidence": [
            {k: v for k, v in ev.items() if k != "locator"} for ev in after["evidence"]]}
        if before_sem != after_sem:
            if unit: semantic.add(unit)
            else: unknown_semantic = True
        elif before["evidence"] != after["evidence"]:
            if unit: locator_only.add(unit)
            else: locator_only |= unit_keys
    locator_only -= semantic
    return semantic, locator_only, unknown_semantic


def _plan_digest(*, name: str, ontology_version: str,
                 pairs: list[tuple[str, str]]) -> str:
    intent = {
        "contract": CONTRACT["contract"],
        "contract_version": int(CONTRACT["version"]),
        "name": name,
        "ontology_version": ontology_version,
        "sources": [
            {"source_id": source_id, "snapshot_id": snapshot_id}
            for source_id, snapshot_id in sorted(pairs)
        ],
    }
    raw = json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ResearchService:
    def __init__(self, context: ResearchContext):
        self.context = context

    def _write_conn(self) -> sqlite3.Connection:
        self.context.require_writable()
        state = verify_schema(self.context)
        if not state["ok"]:
            raise RuntimeError("research schema is not initialized; run migration apply explicitly")
        return self.context.connect()

    # ----- source registry and immutable snapshots -----
    def import_source(
        self, source_path: str | Path, *, text: str, work_id: str | None = None,
        source_file_id: str | None = None, parse_run_id: str | None = None,
        parse_asset_version: int | None = None,
        citation_key: str | None = None, citation_keys: list[str] | None = None,
        parse_quality: str = "unchecked", page_count: int | None = None,
        page_width: float | None = None, page_height: float | None = None,
        page_sizes: list | None = None, page_offsets: list[int] | None = None,
    ) -> dict:
        if parse_quality not in {"unchecked", "passed", "failed"}:
            raise ValueError("invalid parse_quality")
        if page_count is not None and (isinstance(page_count, bool) or
                                       not isinstance(page_count, int) or page_count < 1):
            raise ValueError("page_count must be a positive integer when declared")
        for _geom_name, _geom_value in (("page_width", page_width),
                                        ("page_height", page_height)):
            if _geom_value is not None and (isinstance(_geom_value, bool) or
                                            not isinstance(_geom_value, (int, float))
                                            or _geom_value <= 0):
                raise ValueError(f"{_geom_name} must be a positive number when declared")
        if page_sizes is not None:
            if not isinstance(page_sizes, list) or not page_sizes:
                raise ValueError("page_sizes must be a non-empty list when declared")
            if page_count is not None and len(page_sizes) != page_count:
                raise ValueError("page_sizes must contain exactly one entry per page")
            for index, size in enumerate(page_sizes, start=1):
                if not isinstance(size, dict) or any(
                        isinstance(size.get(key), bool) or
                        not isinstance(size.get(key), (int, float)) or size.get(key) <= 0
                        for key in ("width", "height")):
                    raise ValueError(f"page_sizes[{index - 1}] requires positive width/height")
                rotation = size.get("rotation")
                if rotation is not None and rotation not in {0, 90, 180, 270}:
                    raise ValueError("page_sizes rotation must be 0, 90, 180 or 270")
        if page_offsets is not None:
            if (not isinstance(page_offsets, list) or
                    any(isinstance(v, bool) or not isinstance(v, int) for v in page_offsets)):
                raise ValueError("page_offsets must be a list of integer text offsets")
            if page_count is None or len(page_offsets) != page_count + 1:
                raise ValueError("page_offsets must have page_count + 1 entries")
            if not page_offsets or page_offsets[0] != 0 or page_offsets[-1] != len(text) or \
                    any(a > b for a, b in zip(page_offsets, page_offsets[1:])):
                raise ValueError("page_offsets must be monotonic from 0 through the text length")
        from .storage.runtime import enabled
        asset = str(source_path).startswith('litlib-asset://')
        if enabled() and not asset:
            raise ValueError('immutable research import requires a supported registered asset reference')
        if asset:
            from .storage.references import registered_import
            verified=registered_import(self.context,str(source_path),work_id,source_file_id,parse_run_id,parse_asset_version)
            if text!=verified['text']:raise ValueError('text differs from the fixed registered parse asset')
            src=Path(verified['original_name']);source_sha=verified['sha256']
        else:
            src = Path(source_path).resolve()
            if not src.is_file():raise FileNotFoundError(src)
            source_sha = _sha_bytes(src.read_bytes())
        requested_work_id = work_id
        source_file_id = source_file_id or f"RSF-{source_sha[:16]}"
        work_id = work_id or f"RW-{source_sha[:16]}"
        parse_run_id = parse_run_id or f"RPR-{source_sha[:16]}"
        all_citations = list(dict.fromkeys(
            key.strip() for key in ([citation_key] if citation_key else []) + (citation_keys or [])
            if key and key.strip()
        ))
        citation_key = all_citations[0] if all_citations else None
        source_id = f"RS-{hashlib.sha256(source_file_id.encode()).hexdigest()[:16]}"
        snap_root = self.context.library_root / "research_sources" / source_id
        snap_path = str(source_path) if asset else snap_root / "source" / src.name
        text_sha = _sha_bytes(text.encode("utf-8"))
        now = _now()

        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM research_sources WHERE source_file_id=?", (source_file_id,)
            ).fetchone()
            if existing and existing["source_sha256"] != source_sha:
                raise ValueError("source_file_id already binds different bytes")
            if existing and requested_work_id and requested_work_id != existing["work_id"]:
                raise ValueError("source_file_id already binds a different work_id")
            if not existing:
                if not asset:
                    snap_path.parent.mkdir(parents=True, exist_ok=True)
                    if snap_path.exists() and _sha_bytes(snap_path.read_bytes()) != source_sha:raise FileExistsError(f"snapshot collision: {snap_path}")
                    if not snap_path.exists():shutil.copy2(src, snap_path)
                conn.execute(
                    """INSERT INTO research_sources
                    (id,work_id,source_file_id,citation_key,source_path,snapshot_path,
                     source_sha256,original_name,parse_run_id,parse_exists,parse_quality,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (source_id, work_id, source_file_id, citation_key, str(source_path) if asset else str(src), str(snap_path),
                     source_sha, src.name, parse_run_id, int(bool(text)), parse_quality, now),
                )
            else:
                source_id = existing["id"]
                work_id = existing["work_id"]
                if existing["citation_key"] and existing["citation_key"] not in all_citations:
                    all_citations.insert(0, existing["citation_key"])
                elif not existing["citation_key"] and citation_key:
                    conn.execute("UPDATE research_sources SET citation_key=? WHERE id=?", (citation_key,source_id))

            for index, key in enumerate(all_citations):
                owner = conn.execute("SELECT source_id FROM research_source_citations WHERE key=?", (key,)).fetchone()
                if owner and owner["source_id"] != source_id:
                    raise ValueError(f"citation key already binds another source: {key}")
                conn.execute(
                    "INSERT OR IGNORE INTO research_source_citations(key,source_id,kind,created_at) VALUES (?,?,?,?)",
                    (key,source_id,"primary" if index == 0 else "alias",now),
                )

            parse_rows = conn.execute(
                "SELECT * FROM research_text_snapshots WHERE source_id=? AND parse_run_id=? ORDER BY version",
                (source_id, parse_run_id),
            ).fetchall()
            snapshot = parse_rows[0] if len(parse_rows) == 1 else None
            if len(parse_rows) > 1:
                raise ValueError("parse_run_id has ambiguous legacy snapshot bindings; reconcile lineage before import")
            created = snapshot is None
            if snapshot is None:
                version = conn.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM research_text_snapshots WHERE source_id=?",
                    (source_id,),
                ).fetchone()[0]
                snapshot_id = _id("RTS")
                conn.execute(
                    """INSERT INTO research_text_snapshots
                    (id,source_id,version,source_file_id,parse_run_id,content_text,
                     content_sha256,source_sha256,parse_exists,parse_quality,page_count,
                     page_width,page_height,page_sizes,page_offsets,created_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (snapshot_id, source_id, version, source_file_id, parse_run_id,
                     text, text_sha, source_sha, int(bool(text)), parse_quality, page_count,
                     page_width, page_height,
                     json.dumps(page_sizes, ensure_ascii=False) if page_sizes else None,
                     json.dumps(page_offsets, ensure_ascii=False) if page_offsets is not None else None,
                     now),
                )
            else:
                if (snapshot["content_sha256"] != text_sha or snapshot["source_sha256"] != source_sha or
                        bool(snapshot["parse_exists"]) != bool(text) or snapshot["parse_quality"] != parse_quality):
                    raise ValueError("parse_run_id already binds different text, source bytes or parse quality")
                if page_count is not None and snapshot["page_count"] is not None and \
                        snapshot["page_count"] != page_count:
                    raise ValueError("parse_run_id already binds a different page_count")
                if page_count is not None and snapshot["page_count"] is None:
                    conn.execute("UPDATE research_text_snapshots SET page_count=? WHERE id=?",
                                 (page_count, snapshot["id"]))
                for geom_column, geom_value in (("page_width", page_width),
                                                ("page_height", page_height)):
                    if geom_value is not None and snapshot[geom_column] is not None and \
                            abs(snapshot[geom_column] - float(geom_value)) > 1e-9:
                        raise ValueError(
                            f"parse_run_id already binds a different {geom_column}")
                    if geom_value is not None and snapshot[geom_column] is None:
                        conn.execute(f"UPDATE research_text_snapshots SET {geom_column}=? WHERE id=?",
                                     (geom_value, snapshot["id"]))
                for geom_column, geom_value in (("page_sizes", page_sizes),
                                                ("page_offsets", page_offsets)):
                    if geom_value is None:
                        continue
                    encoded = json.dumps(geom_value, ensure_ascii=False)
                    if snapshot[geom_column] is not None and \
                            json.loads(snapshot[geom_column]) != geom_value:
                        raise ValueError(f"parse_run_id already binds different {geom_column}")
                    if snapshot[geom_column] is None:
                        conn.execute(f"UPDATE research_text_snapshots SET {geom_column}=? WHERE id=?",
                                     (encoded, snapshot["id"]))
                snapshot_id, version = snapshot["id"], snapshot["version"]
            conn.commit()
        return {"source_id": source_id, "work_id": work_id,
                "source_file_id": source_file_id, "parse_run_id": parse_run_id,
                "snapshot_id": snapshot_id, "snapshot_version": version,
                "snapshot_sha256": text_sha, "parse_exists": bool(text),
                "parse_quality": parse_quality,
                "page_count": page_count, "page_sizes": page_sizes,
                "page_offsets": page_offsets,
                "citation_keys": all_citations, "created": created}

    def import_registered_source(self, *, work_id, source_file_id, parse_run_id, version, citation_key=None):
        from .storage.references import asset_reference,registered_import
        reference=asset_reference(source_file_id,1)
        verified=registered_import(self.context,reference,work_id,source_file_id,parse_run_id,version)
        return self.import_source(reference,text=verified['text'],work_id=work_id,source_file_id=source_file_id,parse_run_id=parse_run_id,parse_asset_version=version,citation_key=citation_key)

    @contextmanager
    def materialize_registered_source(self, source_id):
        from .storage.references import decode_reference
        from .storage.runtime import configured_service,required_path
        if self.context.db_path.resolve()!=required_path('LITLIB_RESEARCH_DB',file=True):raise ValueError('matching explicit research context required')
        with closing(self.context.connect(read_only=True)) as c:row=c.execute('SELECT source_file_id,source_path,source_sha256 FROM research_sources WHERE id=?',(source_id,)).fetchone()
        if not row:raise KeyError(source_id)
        identity,version=decode_reference(row['source_path'])
        if identity!=row['source_file_id']:raise ValueError('source asset identity mismatch')
        service=configured_service();binding=service.registry.binding(identity,'pdf',version)
        if binding['sha256']!=row['source_sha256']:raise ValueError('source fingerprint mismatch')
        with service.read(identity,'pdf',version) as p:yield p

    def lookup(self, key: str) -> dict | None:
        with closing(self.context.connect(read_only=True)) as conn:
            source = conn.execute(
                """SELECT s.* FROM research_sources s WHERE s.id=? OR s.work_id=?
                   OR s.source_file_id=? OR s.citation_key=? OR EXISTS (
                     SELECT 1 FROM research_source_citations c WHERE c.source_id=s.id AND c.key=?
                   ) LIMIT 1""", (key, key, key, key, key)
            ).fetchone()
            if not source:
                return None
            snapshots = [dict(r) for r in conn.execute(
                "SELECT id,version,content_sha256,parse_run_id,parse_exists,parse_quality,created_at FROM research_text_snapshots WHERE source_id=? ORDER BY version",
                (source["id"],),
            )]
            for snapshot in snapshots:
                snapshot["parse_exists"] = bool(snapshot["parse_exists"])
            citations = [r[0] for r in conn.execute(
                "SELECT key FROM research_source_citations WHERE source_id=? ORDER BY kind DESC,key", (source["id"],)
            )]
            return {"source": _public_source(source), "citation_keys": citations, "snapshots": snapshots}

    def read_text(self, source_id: str, *, snapshot_id: str | None = None) -> dict:
        with closing(self.context.connect(read_only=True)) as conn:
            if snapshot_id:
                row = conn.execute(
                    "SELECT * FROM research_text_snapshots WHERE source_id=? AND id=?",
                    (source_id, snapshot_id),
                ).fetchone()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_text_snapshots WHERE source_id=? ORDER BY version",
                    (source_id,),
                ).fetchall()
                if len(rows) != 1:
                    raise ValueError("snapshot_id is required when source has zero or multiple snapshots")
                row = rows[0]
            if not row:
                raise KeyError(snapshot_id or source_id)
            result = dict(row)
            result["parse_exists"] = bool(result["parse_exists"])
            return result

    def search(self, query: str, *, limit: int = 50) -> list[dict]:
        literal = query.replace("%", "\\%").replace("_", "\\_")
        like = f"%{literal}%"
        with closing(self.context.connect(read_only=True)) as conn:
            rows = conn.execute(
                """SELECT DISTINCT s.* FROM research_sources s
                   LEFT JOIN research_text_snapshots t ON t.source_id=s.id
                   LEFT JOIN research_source_citations c ON c.source_id=s.id
                   WHERE s.work_id LIKE ? ESCAPE '\\' OR s.source_file_id LIKE ? ESCAPE '\\'
                      OR COALESCE(s.citation_key,'') LIKE ? ESCAPE '\\'
                      OR COALESCE(c.key,'') LIKE ? ESCAPE '\\'
                      OR COALESCE(t.content_text,'') LIKE ? ESCAPE '\\'
                   ORDER BY s.created_at LIMIT ?""", (like, like, like, like, like, limit),
            ).fetchall()
            return [_public_source(r) for r in rows]

    # ----- batch planning/resume -----
    def plan_batch(self, *, request_key: str, name: str, source_ids: list[str],
                   snapshot_ids: dict[str, str] | None = None,
                   ontology_version: str = "autonomy-risk-v1", rerun: bool = False,
                   targets: dict | None = None,
                   release_id: str | None = None) -> dict:
        """Plan a batch.  ``targets`` records the axis/scope contract (A7/B6):
        which layers this plan commits to and which units the delivered
        interpretation must cover.  It is a machine-checkable contract, stored
        normalized as plan_targets_json so completion and usability can be
        verified against the request instead of a free-form dict.

        Shape: ``{"source_record": "required", "interpretation": "required"|
        "not_applicable", "scope": {"unit_keys": ["u1"]}, "per_source":
        {"RS-...": {"interpretation": ..., "scope": ...}}}``.  Unknown keys or
        values are refused at plan time.
        """
        if not request_key or not source_ids:
            raise ValueError("request_key and source_ids are required")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("source_ids must be unique within a batch plan")
        targets = _normalize_targets(targets)
        if targets:
            # B6(R6): 原业务允许“仅整理原文 u1、D 不适用”的局部原文独立完成 —
            # unit scope 绑定在 C 层（原文单元）同样可交付与消费。因此
            # unit_keys + interpretation=not_applicable 不是矛盾，而是合法的
            # 局部 C-only 委托；requested 单元由 C 的 units 覆盖即可。
            # per_source entries must reference sources actually planned here.
            for source_id, entry in (targets.get("per_source") or {}).items():
                if source_id not in source_ids:
                    raise ValueError(
                        f"targets.per_source references source {source_id} which is not "
                        "planned in this batch")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute(
                "SELECT 1 FROM research_ontology_versions WHERE version=?", (ontology_version,)
            ).fetchone():
                raise KeyError(ontology_version)
            pairs: list[tuple[str, str]] = []
            for source_id in source_ids:
                source = conn.execute("SELECT id FROM research_sources WHERE id=?", (source_id,)).fetchone()
                if not source:
                    raise KeyError(source_id)
                requested_snapshot = (snapshot_ids or {}).get(source_id)
                if requested_snapshot:
                    snap = conn.execute(
                        "SELECT id FROM research_text_snapshots WHERE id=? AND source_id=?",
                        (requested_snapshot, source_id),
                    ).fetchone()
                else:
                    snapshots = conn.execute(
                        "SELECT id FROM research_text_snapshots WHERE source_id=? ORDER BY version",
                        (source_id,),
                    ).fetchall()
                    if len(snapshots) > 1:
                        raise ValueError(
                            f"source has multiple snapshots; snapshot_ids[{source_id!r}] is required"
                        )
                    snap = snapshots[0] if snapshots else None
                if not snap:
                    raise ValueError(f"source has no text snapshot: {source_id}")
                pairs.append((source_id, snap["id"]))
            digest = _plan_digest(name=name, ontology_version=ontology_version, pairs=pairs)
            old = conn.execute("SELECT * FROM research_batches WHERE request_key=?", (request_key,)).fetchone()
            if old and not rerun:
                old_digest = old["plan_digest"]
                if not old_digest:
                    old_pairs = [tuple(r) for r in conn.execute(
                        "SELECT source_id,snapshot_id FROM research_batch_items WHERE batch_id=? ORDER BY source_id,snapshot_id",
                        (old["id"],),
                    )]
                    old_digest = _plan_digest(
                        name=old["name"], ontology_version=old["ontology_version"], pairs=old_pairs
                    )
                    conn.execute("UPDATE research_batches SET plan_digest=? WHERE id=?", (old_digest, old["id"]))
                if old_digest != digest:
                    raise ResearchConflictError(
                        "request_key already binds a different canonical plan intent; use rerun=true or a new request_key"
                    )
                items = conn.execute("SELECT COUNT(*) FROM research_batch_items WHERE batch_id=?", (old["id"],)).fetchone()[0]
                conn.commit()
                old_targets = _row_value(old, "plan_targets_json")
                # B5(R6): replaying a request_key with a DIFFERENT intent (other
                # release or targets) is a conflict, not a silent old-plan return.
                old_release = _row_value(old, "release_id")
                # 只比较**显式**给出的意图：省略 release_id/targets 的重放视为
                # 同一意图（钉定值未变），不构成冲突。
                changed = ((release_id is not None and (release_id or None) != (old_release or None))
                           or (targets is not None and
                               (targets or None) != (json.loads(old_targets) if old_targets else None)))
                if changed:
                    raise ResearchConflictError(
                        f"request_key {request_key!r} already binds a plan with "
                        f"release={old_release or 'current'} and its own targets; "
                        "replaying it with a different release/targets is a conflict — "
                        "use a new request_key or rerun=true")
                return {"batch_id": old["id"], "plan_digest": old_digest,
                        "targets": json.loads(old_targets) if old_targets else None,
                        "release_id": old_release,
                        "created": False, "items": items}
            parent = old["id"] if old else None
            actual_key = request_key if not old else f"{request_key}:rerun:{uuid.uuid4().hex[:8]}"
            batch_id, now = _id("RB"), _now()
            # B5: the batch is pinned to the definition release active at plan
            # time — task packages, submissions and later tooling consume this
            # bundle, not whichever release happens to be current later.
            pinned_release = DefinitionService(self.context).resolve_release(release_id)
            conn.execute(
                "INSERT INTO research_batches(id,request_key,name,parent_batch_id,status,ontology_version,plan_digest,plan_targets_json,release_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, actual_key, name, parent, "planned", ontology_version, digest,
                 json.dumps(targets, ensure_ascii=False) if targets is not None else None,
                 pinned_release["id"], now, now),
            )
            for source_id, snapshot_id in pairs:
                conn.execute(
                    "INSERT INTO research_batch_items(id,batch_id,source_id,snapshot_id,status,attempt,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (_id("RBI"), batch_id, source_id, snapshot_id, "planned", 0, now),
                )
            conn.commit()
            return {"batch_id": batch_id, "request_key": actual_key,
                    "parent_batch_id": parent, "plan_digest": digest,
                    "targets": targets,
                    "release_id": pinned_release["id"],
                    "created": True, "items": len(source_ids)}

    def relay_source_into_batch(self, batch_id: str, source_id: str, *,
                                snapshot_id: str | None = None,
                                round_name: str | None = None) -> dict:
        """Relay a staged source into an EXISTING batch lineage (R1 B3).

        v5 batches are immutable plans: the sanctioned change channel is the
        rerun mechanism, so this creates the lineage's next round containing
        the head round's full item set plus the new source — never an
        in-place append, never a silent standalone single-work batch.

        Idempotent: if the source is already planned anywhere in the batch's
        lineage (the batch itself or any successor round), no new round is
        created and the containing batch is returned.
        """
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                batch = conn.execute(
                    "SELECT * FROM research_batches WHERE id=?", (batch_id,)).fetchone()
                if not batch:
                    raise KeyError(batch_id)
                source = conn.execute(
                    "SELECT id FROM research_sources WHERE id=?", (source_id,)).fetchone()
                if not source:
                    raise KeyError(source_id)

                # Lineage = the batch plus all successors (parent_batch_id
                # edges).  Depth-capped guard; the writer only ever links a
                # new child to an existing parent, so cycles cannot form.
                lineage = [batch_id]
                seen = {batch_id}
                frontier = [batch_id]
                for _ in range(64):
                    if not frontier:
                        break
                    marks = ",".join("?" * len(frontier))
                    children = [r["id"] for r in conn.execute(
                        f"SELECT id FROM research_batches "
                        f"WHERE parent_batch_id IN ({marks})", frontier)]
                    frontier = [c for c in children if c not in seen]
                    seen.update(frontier)
                    lineage.extend(frontier)

                marks = ",".join("?" * len(lineage))
                # Prefer the selected batch itself, then any descendant round:
                # deterministic and matches "已在所选批次 → 返回该批次"。
                hit = conn.execute(
                    f"""SELECT bi.batch_id FROM research_batch_items bi
                        WHERE bi.source_id=? AND bi.batch_id IN ({marks})
                        ORDER BY (bi.batch_id = ?) DESC, bi.batch_id LIMIT 1""",
                    [source_id, *lineage, batch_id]).fetchone()
                if hit:
                    hit_batch = conn.execute(
                        """SELECT id, parent_batch_id FROM research_batches
                           WHERE id=?""", (hit["batch_id"],)).fetchone()
                    conn.commit()
                    return {
                        "batch_id": hit["batch_id"],
                        "parent_batch_id": hit_batch["parent_batch_id"],
                        "added": False, "round_created": False,
                        "reason": ("already_planned" if hit["batch_id"] == batch_id
                                   else "already_in_successor"),
                        "items": conn.execute(
                            "SELECT COUNT(*) FROM research_batch_items "
                            "WHERE batch_id=?", (hit["batch_id"],)).fetchone()[0]}

                # Head = latest round in the lineage; the successor accumulates
                # its items so consecutive relays build one coherent chain.
                # A head is a leaf in the parent graph, not merely the row with
                # the newest second-resolution timestamp.  Random ids can sort
                # before their parent when both are created in the same second.
                head = conn.execute(
                    f"""SELECT b.id, b.name, b.request_key, b.ontology_version,
                              b.plan_targets_json, b.release_id
                        FROM research_batches b
                        WHERE b.id IN ({marks})
                          AND NOT EXISTS (
                            SELECT 1 FROM research_batches child
                            WHERE child.parent_batch_id=b.id
                              AND child.id IN ({marks}))
                        ORDER BY b.created_at DESC, b.id DESC LIMIT 1""",
                    [*lineage, *lineage]).fetchone()
                items = conn.execute(
                    """SELECT source_id, snapshot_id FROM research_batch_items
                       WHERE batch_id=?""", (head["id"],)).fetchall()
                pairs = {r["source_id"]: r["snapshot_id"] for r in items}
                if snapshot_id:
                    snap = conn.execute(
                        """SELECT id FROM research_text_snapshots
                           WHERE id=? AND source_id=?""",
                        (snapshot_id, source_id)).fetchone()
                else:
                    snap = conn.execute(
                        """SELECT id FROM research_text_snapshots
                           WHERE source_id=? ORDER BY version DESC LIMIT 1""",
                        (source_id,)).fetchone()
                if not snap:
                    raise ValueError(
                        f"source has no text snapshot: {source_id}")
                pairs[source_id] = snap["id"]
                head_row = dict(head)
                targets_json = head_row["plan_targets_json"]

                # Head discovery and successor insertion must be one atomic
                # operation.  Releasing the write lock here and delegating to
                # plan_batch allowed two callers to create sibling rounds from
                # the same head, each losing the other's newly relayed source.
                next_name = round_name or f"{head_row['name']} · 增补"
                ordered_pairs = list(pairs.items())
                digest = _plan_digest(
                    name=next_name,
                    ontology_version=head_row["ontology_version"],
                    pairs=ordered_pairs,
                )
                next_id, now = _id("RB"), _now()
                actual_key = (
                    f"{head_row['request_key']}:rerun:{uuid.uuid4().hex[:8]}")
                conn.execute(
                    """INSERT INTO research_batches
                       (id,request_key,name,parent_batch_id,status,
                        ontology_version,plan_digest,plan_targets_json,
                        release_id,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (next_id, actual_key, next_name, head_row["id"],
                     "planned", head_row["ontology_version"], digest,
                     targets_json, head_row["release_id"], now, now),
                )
                for planned_source, planned_snapshot in ordered_pairs:
                    conn.execute(
                        """INSERT INTO research_batch_items
                           (id,batch_id,source_id,snapshot_id,status,attempt,updated_at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (_id("RBI"), next_id, planned_source,
                         planned_snapshot, "planned", 0, now),
                    )
                conn.commit()
                targets = None
                if targets_json:
                    try:
                        targets = json.loads(targets_json)
                    except (TypeError, ValueError):
                        targets = None
                return {
                    "batch_id": next_id,
                    "request_key": actual_key,
                    "parent_batch_id": head_row["id"],
                    "plan_digest": digest,
                    "targets": targets,
                    "release_id": head_row["release_id"],
                    "created": True,
                    "items": len(ordered_pairs),
                    "added": True,
                    "round_created": True,
                }
            except Exception:
                conn.rollback()
                raise

    def resume_batch(self, batch_id: str, *, retry_failed: bool = False,
                     worker_owner: str | None = None, lease_seconds: int = 900) -> dict:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        owner = (worker_owner or f"worker-{uuid.uuid4().hex[:8]}").strip()
        if not owner:
            raise ValueError("worker_owner cannot be empty")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            batch = conn.execute("SELECT * FROM research_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                raise KeyError(batch_id)
            eligible = ("planned", "failed") if retry_failed else ("planned",)
            marks = ",".join("?" for _ in eligible)
            now = _now()
            lease_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
            cur = conn.execute(
                f"""UPDATE research_batch_items
                    SET status='running',attempt=attempt+1,last_error=NULL,worker_owner=?,
                        started_at=?,heartbeat_at=?,lease_expires_at=?,updated_at=?
                    WHERE batch_id=? AND status IN ({marks})""",
                (owner, now, now, lease_expires_at, now, batch_id, *eligible),
            )
            if cur.rowcount:
                conn.execute("UPDATE research_batches SET status='running',updated_at=? WHERE id=?", (now, batch_id))
            items = [dict(r) for r in conn.execute(
                """SELECT * FROM research_batch_items
                   WHERE batch_id=? AND status='running' AND worker_owner=? AND heartbeat_at=?
                   ORDER BY id""", (batch_id, owner, now)
            )]
            state = None if cur.rowcount else self._reconcile_batch(conn, batch_id)
            conn.commit()
            return {"batch_id": batch_id, "worker_owner": owner,
                    "lease_expires_at": lease_expires_at,
                    "resumed": cur.rowcount, "items": items,
                    "status": "running" if cur.rowcount else state["status"]}

    def recover_running(self, batch_id: str, *, older_than_seconds: int = 900,
                        worker_owner: str | None = None) -> dict:
        """Explicitly release expired/crashed running items back to planned.

        Recovery is never implicit in resume/reconcile.  The prior attempt and
        owner/timestamps remain observable through ``last_error`` and the
        incremented attempt on the next resume.
        """
        if older_than_seconds < 0:
            raise ValueError("older_than_seconds cannot be negative")
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat(timespec="seconds")
        now = _now()
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM research_batches WHERE id=?", (batch_id,)).fetchone():
                raise KeyError(batch_id)
            where = ["batch_id=?", "status='running'",
                     "(lease_expires_at<=? OR (lease_expires_at IS NULL AND COALESCE(heartbeat_at,started_at,updated_at)<=?))"]
            params: list[Any] = [batch_id, now, cutoff]
            if worker_owner:
                where.append("worker_owner=?")
                params.append(worker_owner)
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM research_batch_items WHERE " + " AND ".join(where) + " ORDER BY id", params
            )]
            for item in rows:
                prior_owner = item.get("worker_owner") or "unknown"
                note = f"explicit crash recovery from owner={prior_owner} at {now}"
                conn.execute(
                    """UPDATE research_batch_items SET status='planned',last_error=?,worker_owner=NULL,
                       started_at=NULL,heartbeat_at=NULL,lease_expires_at=NULL,
                       recovery_count=recovery_count+1,last_recovery_at=?,last_recovery_note=?,updated_at=?
                       WHERE id=?""",
                    (note, now, note, now, item["id"]),
                )
            result = self._reconcile_batch(conn, batch_id)
            conn.commit()
            return {**result, "recovered": len(rows),
                    "recovered_item_ids": [item["id"] for item in rows]}

    def heartbeat_batch_item(self, batch_id: str, source_id: str, *,
                             worker_owner: str, lease_seconds: int = 900) -> dict:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if not worker_owner.strip():
            raise ValueError("worker_owner cannot be empty")
        now = _now()
        lease_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        with closing(self._write_conn()) as conn:
            cur = conn.execute(
                """UPDATE research_batch_items SET heartbeat_at=?,lease_expires_at=?,updated_at=?
                   WHERE batch_id=? AND source_id=? AND status='running' AND worker_owner=?""",
                (now, lease_expires_at, now, batch_id, source_id, worker_owner),
            )
            if cur.rowcount != 1:
                raise ValueError("running item is not leased to this worker_owner")
            conn.commit()
            return {"batch_id": batch_id, "source_id": source_id,
                    "worker_owner": worker_owner, "heartbeat_at": now,
                    "lease_expires_at": lease_expires_at}

    def _authorize_item_mutation(
        self, conn: sqlite3.Connection, item: sqlite3.Row, *, action: str,
        worker_owner: str | None, attempt: int | None,
        manual_action: bool, manual_reason: str | None,
    ) -> str:
        now = _now()
        if manual_action:
            if worker_owner is not None or attempt is not None:
                raise ValueError("manual_action cannot include worker_owner or attempt")
            reason = (manual_reason or "").strip()
            if not reason:
                raise ValueError("manual_action requires a non-empty manual_reason")
            mode = "manual"
        else:
            if worker_owner is None or attempt is None:
                raise ValueError("worker mutation requires worker_owner and attempt fencing token")
            if (item["status"] != "running" or item["worker_owner"] != worker_owner or
                    item["attempt"] != attempt or not item["lease_expires_at"] or
                    item["lease_expires_at"] <= now):
                raise ResearchConflictError("stale or invalid worker lease/fencing token")
            reason = None
            mode = "worker"
        conn.execute(
            """INSERT INTO research_batch_item_events
               (id,item_id,action,submission_mode,worker_owner,attempt,reason,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (_id("RBIE"), item["id"], action, mode, worker_owner, attempt, reason, now),
        )
        return mode

    def _reconcile_batch(self, conn: sqlite3.Connection, batch_id: str) -> dict:
        batch = conn.execute("SELECT id FROM research_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise KeyError(batch_id)
        items = conn.execute(
            """SELECT bi.*,s.source_file_id AS expected_source_file_id,
                      s.source_sha256 AS expected_source_sha256
               FROM research_batch_items bi
               LEFT JOIN research_sources s ON s.id=bi.source_id
               WHERE bi.batch_id=? ORDER BY bi.id""", (batch_id,)
        ).fetchall()
        counts = {row[0]: row[1] for row in conn.execute(
            "SELECT status,COUNT(*) FROM research_batch_items WHERE batch_id=? GROUP BY status",
            (batch_id,),
        )}
        total = sum(counts.values())
        anomalies: list[dict] = []
        safe_repairs: list[dict] = []
        now = _now()
        for item in items:
            anomaly_start = len(anomalies)
            def anomaly(code: str, detail: str) -> None:
                anomalies.append({"item_id": item["id"], "source_id": item["source_id"],
                                  "code": code, "detail": detail})

            snapshot = conn.execute("SELECT * FROM research_text_snapshots WHERE id=?", (item["snapshot_id"],)).fetchone()
            if not item["expected_source_file_id"]:
                anomaly("missing_source", "batch item source does not exist")
            if not snapshot:
                anomaly("missing_snapshot", "batch item snapshot does not exist")
            elif snapshot["source_id"] != item["source_id"]:
                anomaly("snapshot_source_mismatch", "snapshot belongs to another source")
            elif (snapshot["source_file_id"] != item["expected_source_file_id"] or
                  snapshot["source_sha256"] != item["expected_source_sha256"]):
                anomaly("snapshot_binding_mismatch", "snapshot source-file/hash binding disagrees with source")
            elif _sha_bytes(snapshot["content_text"].encode("utf-8")) != snapshot["content_sha256"]:
                anomaly("snapshot_content_hash_mismatch", "snapshot content no longer matches its immutable hash")

            source_record = None
            if item["source_record_id"]:
                source_record = conn.execute(
                    "SELECT * FROM research_source_records WHERE id=?", (item["source_record_id"],)
                ).fetchone()
                if not source_record:
                    anomaly("missing_source_record", "source_record_id does not exist")
                elif (source_record["batch_id"] != batch_id or
                      source_record["source_id"] != item["source_id"] or
                      source_record["snapshot_id"] != item["snapshot_id"] or
                      (snapshot and source_record["snapshot_sha256"] != snapshot["content_sha256"]) or
                      source_record["source_file_id"] != item["expected_source_file_id"] or
                      (snapshot and source_record["parse_run_id"] != snapshot["parse_run_id"])):
                    anomaly("source_record_binding_mismatch", "current source record breaks batch/source/snapshot/hash/parse binding")
                elif source_record["validity_status"] != "active":
                    anomaly("source_record_not_active", "batch item points to a non-active source-record revision")
                else:
                    head = conn.execute(
                        """SELECT id FROM research_source_records
                           WHERE batch_id=? AND source_id=? ORDER BY version DESC LIMIT 1""",
                        (batch_id, item["source_id"]),
                    ).fetchone()
                    if not head or head["id"] != source_record["id"]:
                        anomaly("source_record_not_head", "batch item does not point to the latest source-record revision")
                if source_record and conn.execute(
                    """SELECT 1 FROM research_claims c JOIN research_evidence e ON e.claim_id=c.id
                       WHERE c.record_layer='source_record' AND c.record_id=? AND e.snapshot_id<>? LIMIT 1""",
                    (source_record["id"], item["snapshot_id"]),
                ).fetchone():
                    anomaly("source_evidence_snapshot_mismatch", "source-record evidence points outside its bound snapshot")
            elif item["status"] == "submitted":
                anomaly("submitted_without_source_record", "submitted item lacks a source record")

            interpretation = None
            if item["interpretation_id"]:
                interpretation = conn.execute(
                    "SELECT * FROM research_interpretations WHERE id=?", (item["interpretation_id"],)
                ).fetchone()
                if not interpretation:
                    anomaly("missing_interpretation", "interpretation_id does not exist")
                elif (interpretation["batch_id"] != batch_id or
                      interpretation["source_id"] != item["source_id"] or
                      interpretation["source_record_id"] != item["source_record_id"] or
                      interpretation["snapshot_id"] != item["snapshot_id"] or
                      (snapshot and interpretation["snapshot_sha256"] != snapshot["content_sha256"]) or
                      interpretation["source_file_id"] != item["expected_source_file_id"] or
                      (snapshot and interpretation["parse_run_id"] != snapshot["parse_run_id"])):
                    anomaly("interpretation_binding_mismatch", "current interpretation breaks item/source-record/snapshot/hash/parse binding")
                elif interpretation["validity_status"] == "superseded":
                    anomaly("interpretation_superseded", "batch item points to a superseded interpretation revision")
                else:
                    head = conn.execute(
                        """SELECT id FROM research_interpretations
                           WHERE batch_id=? AND source_record_id=? ORDER BY version DESC LIMIT 1""",
                        (batch_id, item["source_record_id"]),
                    ).fetchone()
                    if not head or head["id"] != interpretation["id"]:
                        anomaly("interpretation_not_head", "batch item does not point to the latest interpretation revision")
                if interpretation and conn.execute(
                    """SELECT 1 FROM research_claims c JOIN research_evidence e ON e.claim_id=c.id
                       WHERE c.record_layer='interpretation' AND c.record_id=? AND e.snapshot_id<>? LIMIT 1""",
                    (interpretation["id"], item["snapshot_id"]),
                ).fetchone():
                    anomaly("interpretation_evidence_snapshot_mismatch", "interpretation evidence points outside its bound snapshot")
                # B6: an explicit unit scope in the plan is a checkable contract —
                # delivered content (C units or D scope) must cover the
                # requested units; otherwise the gap is reported, never silently
                # accepted.
                requested_units = ((_requested_scope_targets(conn, batch_id, item["source_id"]) or {})
                                   .get("scope") or {}).get("unit_keys") or []
                if requested_units and len(anomalies) == anomaly_start and \
                        (interpretation is not None or source_record is not None):
                    interpretation_required = not _interpretation_not_required(
                        conn, batch_id, item["source_id"], source_record)
                    # C-only commissions are covered by C units.  Once D is
                    # explicitly required, however, its own input_refs must
                    # cover the requested units; C coverage cannot stand in
                    # for an incomplete interpretation deliverable.
                    delivered_refs: set = set()
                    if source_record is not None and not interpretation_required:
                        try:
                            sr_units = json.loads(source_record["payload_json"]).get("units") or []
                            delivered_refs |= {str(u.get("unit_key")) for u in sr_units
                                                if isinstance(u, dict) and u.get("unit_key")}
                        except (TypeError, ValueError):
                            pass
                    if interpretation is not None:
                        try:
                            delivered_scope = json.loads(interpretation["scope_json"] or "null") or {}
                        except (TypeError, ValueError):
                            delivered_scope = {}
                        delivered_refs |= set(delivered_scope.get("input_refs") or [])
                    missing_units = sorted(set(requested_units) - delivered_refs)
                    if missing_units:
                        anomaly("requested_unit_scope_unmet",
                                f"plan requests units {requested_units} but the delivered "
                                f"content covers only {sorted(delivered_refs) or 'nothing'}; "
                                f"missing {missing_units}")
            elif item["status"] == "submitted":
                # B6: the request target decides completion.  An interpretation
                # is not forced when the plan marks it not_applicable, or when
                # the C record itself is background/not_applicable.
                if not _interpretation_not_required(conn, batch_id, item["source_id"], source_record):
                    anomaly("submitted_without_interpretation", "submitted item lacks an interpretation")
            if (source_record and interpretation and item["status"] != "submitted" and
                    len(anomalies) == anomaly_start):
                safe_repairs.append({"item_id": item["id"], "action": "set_status_submitted"})
            if item["status"] == "running" and item["lease_expires_at"] and item["lease_expires_at"] <= now:
                safe_repairs.append({"item_id": item["id"], "action": "recover_running"})
            # B6: C 已提交且任务范围声明 D 不适用 —— 该项随 C 关闭，不强求写
            # D 层，也不把批永久卡在 running。这是计划契约推导出的确定性
            # 关闭，不需要人工干预。
            if (item["status"] == "running" and source_record is not None
                    and item["interpretation_id"] is None
                    and len(anomalies) == anomaly_start
                    and _interpretation_not_required(conn, batch_id, item["source_id"], source_record)):
                conn.execute(
                    """UPDATE research_batch_items SET status='submitted',worker_owner=NULL,
                       started_at=NULL,heartbeat_at=NULL,lease_expires_at=NULL,last_error=NULL,
                       updated_at=? WHERE id=?""", (now, item["id"]))
                safe_repairs.append({"item_id": item["id"], "source_id": item["source_id"],
                                     "action": "close_without_interpretation"})
            # B6: the plan explicitly requires an interpretation and the item
            # TERMINATED without one (worker abandoned, failed, or lease
            # expired) — the conflict is reported, never silently completed.
            if (item["status"] in ("running", "failed") and source_record is not None
                    and item["interpretation_id"] is None
                    and len(anomalies) == anomaly_start
                    and not _interpretation_not_required(conn, batch_id, item["source_id"], source_record)
                    and (item["status"] == "failed"
                         or (item["lease_expires_at"] and item["lease_expires_at"] <= now))):
                anomaly("requested_interpretation_missing",
                        "plan requests an interpretation (targets.interpretation=required) "
                        "but the item ended without one; the delegated scope is unmet")

        if total:
            # the B6 closure above changes item states: recount before deriving
            # the batch status so a fully-closed batch reports completed
            counts = {row[0]: row[1] for row in conn.execute(
                "SELECT status,COUNT(*) FROM research_batch_items WHERE batch_id=? GROUP BY status",
                (batch_id,),
            )}
        if total and counts.get("submitted", 0) == total and not anomalies:
            status = "completed"
        elif (anomalies or counts.get("failed", 0)) and not (counts.get("planned", 0) or counts.get("running", 0)):
            status = "completed_with_errors"
        elif counts.get("running", 0) or counts.get("submitted", 0):
            status = "running"
        else:
            status = "planned"
        conn.execute("UPDATE research_batches SET status=?,updated_at=? WHERE id=?", (status, now, batch_id))
        return {"batch_id": batch_id, "status": status, "total": total,
                "counts": counts, "anomalies": anomalies, "safe_repairs": safe_repairs}

    def reconcile_batch(self, batch_id: str) -> dict:
        with closing(self._write_conn()) as conn:
            result = self._reconcile_batch(conn, batch_id)
            conn.commit()
            return result

    def mark_batch_item_failed(self, batch_id: str, source_id: str, *, error: str,
                               worker_owner: str | None = None, attempt: int | None = None,
                               manual_action: bool = False,
                               manual_reason: str | None = None) -> dict:
        if not error.strip():
            raise ValueError("failure error is required")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            item = conn.execute(
                "SELECT * FROM research_batch_items WHERE batch_id=? AND source_id=?",
                (batch_id, source_id),
            ).fetchone()
            if not item:
                raise KeyError(f"{batch_id}/{source_id}")
            mode = self._authorize_item_mutation(
                conn, item, action="mark_failed", worker_owner=worker_owner, attempt=attempt,
                manual_action=manual_action, manual_reason=manual_reason,
            )
            conn.execute(
                """UPDATE research_batch_items SET status='failed',last_error=?,worker_owner=NULL,
                   started_at=NULL,heartbeat_at=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?""",
                (error.strip(), _now(), item["id"]),
            )
            result = self._reconcile_batch(conn, batch_id)
            conn.commit()
            return {**result, "source_id": source_id, "last_error": error.strip(),
                    "submission_mode": mode}

    # ----- versioned records and evidence -----
    def _binding(self, conn: sqlite3.Connection, source_id: str, snapshot_id: str) -> tuple[dict, dict]:
        source = _row(conn.execute("SELECT * FROM research_sources WHERE id=?", (source_id,)).fetchone())
        snap = _row(conn.execute(
            "SELECT * FROM research_text_snapshots WHERE id=? AND source_id=?", (snapshot_id, source_id)
        ).fetchone())
        if not source or not snap:
            raise KeyError("source/snapshot binding not found")
        if (snap["source_file_id"] != source["source_file_id"] or
                snap["source_sha256"] != source["source_sha256"]):
            raise ValueError("source/snapshot source-file or hash binding mismatch")
        return source, snap

    def _insert_claims(self, conn: sqlite3.Connection, *, layer: str, record_id: str,
                       snapshot: dict, claims: list[dict]) -> None:
        if not claims:
            raise ValueError("at least one evidence-backed claim is required")
        content = snapshot["content_text"]
        now = _now()
        for item in claims:
            key, claim_text = str(item.get("key", "")).strip(), str(item.get("text", "")).strip()
            evidence = item.get("evidence") or []
            if not key or not claim_text or not evidence:
                raise ValueError("each claim needs key, text and evidence")
            claim_id = _id("RC")
            conn.execute(
                "INSERT INTO research_claims(id,record_layer,record_id,claim_key,claim_text,created_at) VALUES (?,?,?,?,?,?)",
                (claim_id, layer, record_id, key, claim_text, now),
            )
            for ev in evidence:
                quote = str(ev.get("quote", ""))
                if not quote:
                    raise ValueError(f"claim {key} has empty evidence quote")
                start = ev.get("start_offset")
                if start is None:
                    start = content.find(quote)
                end = ev.get("end_offset", start + len(quote) if start >= 0 else -1)
                if start < 0 or end != start + len(quote) or content[start:end] != quote:
                    raise ValueError(f"claim {key} evidence anchor does not match bound snapshot")
                # U19: the structured locator is validated against the SAME bound
                # snapshot at the C/D entry — an out-of-range page/line, unknown
                # anchor, foreign source_version or illegal kind cannot be stored,
                # let alone approved.
                locator = validate_locator(ev.get("locator"), {
                    "content_text": content,
                    "version": snapshot.get("version"),
                    "page_count": snapshot.get("page_count"),
                    "page_width": snapshot.get("page_width"),
                    "page_height": snapshot.get("page_height"),
                    "page_sizes": json.loads(snapshot["page_sizes"] or "null")
                    if snapshot.get("page_sizes") else None,
                    "page_offsets": json.loads(snapshot["page_offsets"] or "null")
                    if snapshot.get("page_offsets") else None,
                    "start_offset": start,
                }) if ev.get("locator") else {}
                conn.execute(
                    "INSERT INTO research_evidence(id,claim_id,snapshot_id,quote,start_offset,end_offset,locator_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (_id("RE"), claim_id, snapshot["id"], quote, start, end,
                     json.dumps(locator, ensure_ascii=False), now),
                )

    def submit_source_record(self, *, batch_id: str, source_id: str, snapshot_id: str,
                             schema_version: str, payload: dict, claims: list[dict],
                             supersedes_id: str | None = None,
                             worker_owner: str | None = None, attempt: int | None = None,
                             manual_action: bool = False,
                             manual_reason: str | None = None,
                             release_id: str | None = None,
                             expected_head_id: str | None = None,
                             feedback_id: str | None = None,
                             submitted_by: str | None = None,
                             environment_id: str | None = None) -> dict:
        _require_environment(self.context, environment_id)
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # B5(R6): an IMPLICIT submission obeys the batch's pinned release —
            # the task the worker accepted fixes the definitions it must meet,
            # regardless of which bundle happens to be current later.
            if release_id is None:
                batch_row = conn.execute(
                    "SELECT release_id FROM research_batches WHERE id=?", (batch_id,)).fetchone()
                batch_pin = batch_row["release_id"] if batch_row and "release_id" in batch_row.keys() else None
                if batch_pin:
                    release_id = batch_pin
            bound_release_id, definition_refs_json = _resolve_release_binding(
                self.context, release_id, ["source_record"])
            _check_explicit_release_change(conn, batch_id, bound_release_id, manual_action,
                                           manual_reason, "source record")
            ref = next(r for r in json.loads(definition_refs_json) if r["layer"] == "source_record")
            definition = DefinitionService(self.context).get_definition("source_record", ref["version"])
            validate_payload_against_definition("source_record", payload, definition["payload"])
            source, snap = self._binding(conn, source_id, snapshot_id)
            item = conn.execute(
                "SELECT * FROM research_batch_items WHERE batch_id=? AND source_id=? AND snapshot_id=?",
                (batch_id, source_id, snapshot_id),
            ).fetchone()
            if not item:
                raise ValueError("source is not planned in this batch with this snapshot")
            mode = self._authorize_item_mutation(
                conn, item, action="submit_source_record", worker_owner=worker_owner, attempt=attempt,
                manual_action=manual_action, manual_reason=manual_reason,
            )
            # B2: the record's generation origin is pinned here, once, from the
            # submitting identity — reviewer independence is later checked
            # against THIS value, never against the batch item's current holder.
            # A NEW record may not drop its obtainable origin: omitting it must
            # not later pass as "historical unknown" (R4 B2).
            origin_submitter = (worker_owner or "").strip() or (submitted_by or "").strip() or None
            if origin_submitter is None:
                raise ValueError(
                    "new source records require a generation origin: pass worker_owner "
                    "or submitted_by; omitting it must not masquerade as historical unknown")
            latest = conn.execute(
                "SELECT * FROM research_source_records WHERE batch_id=? AND source_id=? ORDER BY version DESC LIMIT 1",
                (batch_id, source_id),
            ).fetchone()
            if expected_head_id is not None and (latest["id"] if latest else None) != expected_head_id:
                raise ValueError("expected_head_id does not match the current source-record head")
            if latest and not supersedes_id:
                same = (
                    latest["schema_version"] == schema_version
                    and _row_value(latest, "release_id") == bound_release_id
                    and json.loads(latest["payload_json"]) == payload
                    and _canonical_claims(self._record_claims(conn, "source_record", latest["id"])) == _canonical_claims(claims)
                )
                if same:
                    if latest["validity_status"] != "active":
                        raise ValueError("idempotent retry requires the current active source-record head")
                    conn.execute(
                        """UPDATE research_batch_items SET
                           status=CASE WHEN interpretation_id IS NULL THEN 'running' ELSE 'submitted' END,
                           source_record_id=?,last_error=NULL,updated_at=? WHERE id=?""",
                        (latest["id"], _now(), item["id"]),
                    )
                    self._reconcile_batch(conn, batch_id)
                    result = {
                        "record_id": latest["id"], "version": latest["version"],
                        "source_file_id": latest["source_file_id"], "parse_run_id": latest["parse_run_id"],
                        "snapshot_sha256": latest["snapshot_sha256"],
                        "validation_status": latest["validation_status"],
                        "agent_review_status": latest["agent_review_status"],
                        "human_adoption_status": latest["human_adoption_status"],
                        "validity_status": latest["validity_status"], "created": False,
                        "submission_mode": mode,
                        "release_id": _row_value(latest, "release_id"),
                    }
                    record_operation_effect(conn, result)
                    conn.commit()
                    return result
                raise ValueError("non-identical source submission requires supersedes_id")
            if supersedes_id:
                old = conn.execute(
                    "SELECT * FROM research_source_records WHERE id=? AND batch_id=? AND source_id=?",
                    (supersedes_id, batch_id, source_id),
                ).fetchone()
                if not old:
                    raise KeyError(supersedes_id)
                if (not latest or supersedes_id != latest["id"] or
                        latest["validity_status"] != "active" or
                        item["source_record_id"] != latest["id"]):
                    raise ValueError("supersedes_id must be the current active source-record head")
            elif latest:
                raise ValueError("existing source record requires supersedes_id")
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM research_source_records WHERE batch_id=? AND source_id=?",
                (batch_id, source_id),
            ).fetchone()[0]
            record_id, now = _id("RSR"), _now()
            conn.execute(
                """INSERT INTO research_source_records
                (id,batch_id,source_id,source_file_id,parse_run_id,snapshot_id,snapshot_sha256,
                 schema_version,version,payload_json,validation_status,agent_review_status,
                 human_adoption_status,validity_status,supersedes_id,layer,content_state,
                 release_id,definition_refs_json,feedback_id,submitted_by,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,'passed','pending','pending','active',?,
                        'source_record','needs_review',?,?,?,?,?,?)""",
                (record_id,batch_id,source_id,source["source_file_id"],snap["parse_run_id"],
                 snapshot_id,snap["content_sha256"],schema_version,version,
                 json.dumps(payload,ensure_ascii=False),supersedes_id,
                 bound_release_id,definition_refs_json,feedback_id,
                 origin_submitter,now,now),
            )
            self._insert_claims(conn, layer="source_record", record_id=record_id, snapshot=snap, claims=claims)
            self._link_feedback_row(conn, feedback_id, record_id, now)
            baseline_preserved = False
            if supersedes_id:
                predecessor = conn.execute(
                    "SELECT content_state,validity_status FROM research_source_records WHERE id=?",
                    (supersedes_id,)).fetchone()
                if predecessor and predecessor["content_state"] == "stable" \
                        and predecessor["validity_status"] == "active":
                    # version policy: candidate and usable baseline are kept apart.
                    # A pending candidate never removes the old stable baseline;
                    # the switch happens when this candidate is approved.
                    baseline_preserved = True
                else:
                    conn.execute(
                        "UPDATE research_source_records SET validity_status='superseded',updated_at=? WHERE id=?",
                        (now, supersedes_id),
                    )
                    conn.execute(
                        "UPDATE research_interpretations SET validity_status='stale',updated_at=? WHERE source_record_id=? AND validity_status='active'",
                        (now, supersedes_id),
                    )
            conn.execute(
                """UPDATE research_batch_items SET status='running',source_record_id=?,interpretation_id=NULL,
                   last_error=NULL,updated_at=? WHERE id=?""",
                (record_id,now,item["id"]),
            )
            result = {"record_id": record_id, "version": version,
                      "source_file_id": source["source_file_id"], "parse_run_id": snap["parse_run_id"],
                      "snapshot_sha256": snap["content_sha256"], "validation_status": "passed",
                      "agent_review_status": "pending", "human_adoption_status": "pending",
                      "validity_status": "active", "created": True,
                      "submission_mode": mode, "baseline_preserved": baseline_preserved,
                      "release_id": bound_release_id}
            record_operation_effect(conn, result)
            conn.commit()
            return result

    def submit_interpretation(self, *, batch_id: str, source_record_id: str,
                              schema_version: str, ontology_version: str,
                              ontology_keys: list[str], payload: dict, claims: list[dict],
                              supersedes_id: str | None = None,
                              worker_owner: str | None = None, attempt: int | None = None,
                              manual_action: bool = False,
                              manual_reason: str | None = None,
                              release_id: str | None = None,
                              expected_head_id: str | None = None,
                              feedback_id: str | None = None,
                              scope: dict | None = None,
                              submitted_by: str | None = None,
                              metadata_record_id: str | None = None,
                              environment_id: str | None = None) -> dict:
        _require_environment(self.context, environment_id)
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # B5(R6): an IMPLICIT submission obeys the batch's pinned release.
            if release_id is None:
                batch_row = conn.execute(
                    "SELECT release_id FROM research_batches WHERE id=?", (batch_id,)).fetchone()
                batch_pin = batch_row["release_id"] if batch_row and "release_id" in batch_row.keys() else None
                if batch_pin:
                    release_id = batch_pin
            bound_release_id, definition_refs_json = _resolve_release_binding(
                self.context, release_id, ["interpretation"])
            _check_explicit_release_change(conn, batch_id, bound_release_id, manual_action,
                                           manual_reason, "interpretation")
            # B5: the ACTUAL ontology obeys the bound release — a caller cannot
            # pair an old bundle with a newer ontology version or concept set.
            _definition_service = DefinitionService(self.context)
            _release = _definition_service.resolve_release(bound_release_id)
            _ontology_ref = next(r for r in _release["definition_refs"] if r["layer"] == "ontology")
            _ontology_def = _definition_service.get_definition("ontology", _ontology_ref["version"])
            _released_ontology = (_ontology_def["payload"] or {}).get("ontology_version")
            if _released_ontology and ontology_version != _released_ontology:
                raise ValueError(
                    f"ontology_version {ontology_version!r} is not the version bound by "
                    f"release {bound_release_id} ({_released_ontology!r}); the release "
                    "fixes the actual ontology for its submissions")
            record = _row(conn.execute(
                "SELECT * FROM research_source_records WHERE id=? AND batch_id=?", (source_record_id,batch_id)
            ).fetchone())
            if not record:
                raise KeyError(source_record_id)
            item = conn.execute(
                "SELECT * FROM research_batch_items WHERE batch_id=? AND source_id=?",
                (batch_id, record["source_id"]),
            ).fetchone()
            if not item or item["source_record_id"] != source_record_id:
                raise ValueError("interpretation must bind the batch item's current source record")
            mode = self._authorize_item_mutation(
                conn, item, action="submit_interpretation", worker_owner=worker_owner, attempt=attempt,
                manual_action=manual_action, manual_reason=manual_reason,
            )
            # B2: generation origin pinned from the submitting identity (see
            # submit_source_record) — never re-derived from the claim holder;
            # new records may not drop an obtainable origin (R4 B2).
            origin_submitter = (worker_owner or "").strip() or (submitted_by or "").strip() or None
            if origin_submitter is None:
                raise ValueError(
                    "new interpretations require a generation origin: pass worker_owner "
                    "or submitted_by; omitting it must not masquerade as historical unknown")
            # U24/PLATFORM-004: pin the metadata record this interpretation
            # actually consumed (same work only) so later openness changes
            # trace to their dependents.  Layered gate: an omitted pin keeps
            # the v5-compatible submission path (the record is flagged and can
            # never be approved or recommended until a revision pins a head),
            # while a provided pin must be the work's current active A head —
            # wrong-work or stale pins are rejected at the entry.
            source_work = conn.execute(
                "SELECT work_id FROM research_sources WHERE id=?", (record["source_id"],)
            ).fetchone()
            pinned_metadata_id = (metadata_record_id or "").strip() or None
            validate_metadata_pin_for_submission(
                conn, work_id=source_work["work_id"],
                pinned_record_id=pinned_metadata_id)
            # B6: ONE scope authority.  The stored scope (the `scope`
            # parameter) is what reconcile consumes; a payload.scope that
            # disagrees is a conflict, and a payload.scope without the
            # parameter is adopted so delivery and consumption never read two
            # different scope truths.
            payload_scope = payload.get("scope") if isinstance(payload, dict) else None
            if scope is not None and payload_scope is not None and payload_scope != scope:
                raise ValueError(
                    "payload.scope and the scope parameter disagree; a record cannot "
                    "carry two scope truths")
            if scope is None and isinstance(payload_scope, dict):
                scope = payload_scope
            if record["validity_status"] != "active" or record["validation_status"] != "passed":
                raise ValueError("interpretation requires the current passed, active source record")
            ref = next(r for r in json.loads(definition_refs_json) if r["layer"] == "interpretation")
            definition = DefinitionService(self.context).get_definition("interpretation", ref["version"])
            validate_payload_against_definition("interpretation", payload, definition["payload"])
            # scope.input_refs and association scope_refs must resolve against
            # real units/shared items of the bound source record — dangling
            # references are invalid payloads (B5 covers associations too).
            sr_payload = json.loads(record["payload_json"])
            known_unit_keys = {row[0] for row in conn.execute(
                "SELECT unit_key FROM research_units WHERE source_record_id=? AND validity_status='active'",
                (source_record_id,))}
            shared_keys = {str(item.get("key") or item.get("kind") or "")
                           for item in sr_payload.get("shared_items") or [] if isinstance(item, dict)}
            unit_payload_keys = {
                str(u.get("unit_key")) for u in sr_payload.get("units") or [] if isinstance(u, dict)
            } | known_unit_keys
            declared_refs = set((payload.get("scope") or {}).get("input_refs") or [])
            dangling = sorted(declared_refs - shared_keys - unit_payload_keys)
            if dangling:
                raise ValueError(f"scope.input_refs do not resolve in the bound source record: {dangling}")
            # B5: an association claims its aspects hold for ALL of its
            # scope_refs — those units must exist in the bound source record,
            # otherwise the claim would ride on units that were never built.
            for assoc_index, assoc in enumerate(payload.get("associations") or []):
                assoc_refs = (assoc or {}).get("scope_refs") or []
                dangling_assoc = sorted({str(r) for r in assoc_refs}
                                        - shared_keys - unit_payload_keys)
                if dangling_assoc:
                    raise ValueError(
                        f"associations[{assoc_index}].scope_refs do not resolve in the "
                        f"bound source record: {dangling_assoc}")
            source, snap = self._binding(conn, record["source_id"], record["snapshot_id"])
            if (record["snapshot_sha256"] != snap["content_sha256"] or
                    record["source_file_id"] != source["source_file_id"] or
                    record["parse_run_id"] != snap["parse_run_id"] or
                    item["snapshot_id"] != snap["id"]):
                raise ValueError("source record breaks batch/source/snapshot/hash/parse binding")
            ontology = conn.execute("SELECT payload_json FROM research_ontology_versions WHERE version=?", (ontology_version,)).fetchone()
            if not ontology:
                raise KeyError(ontology_version)
            ontology_payload = json.loads(ontology["payload_json"])
            unknown_keys = sorted(set(ontology_keys) - _concept_ids(ontology_payload))
            if unknown_keys:
                raise ValueError(f"ontology_keys not defined by {ontology_version}: {unknown_keys}")
            dimensions = ontology_payload.get("dimensions") or {}
            for dimension in ("mapping_status", "update_object", "research_role"):
                value = payload.get(dimension) if isinstance(payload, dict) else None
                allowed = set(dimensions.get(dimension) or [])
                if value is not None and value not in allowed:
                    raise ValueError(f"{dimension} not defined by {ontology_version}: {value}")
            # §13.4: associations carry the released controlled vocabularies, and
            # root summaries derive from them — root fields are not parallel
            # writable truths alongside associations.
            associations = payload.get("associations")
            if associations:
                # B5(R6): the association vocabularies are the WHOLE released
                # bundle's merged result (every layer's declared overrides),
                # not just this layer's own defaults.
                _bundle_vocab = DefinitionService(self.context).released_vocabularies(
                    bound_release_id)
                validate_associations(associations, _concept_ids(ontology_payload),
                                      vocabularies=_bundle_vocab)
                derived = derive_association_summaries(associations)
                if sorted(set(ontology_keys)) != derived.get("ontology_keys", []):
                    raise ValueError(
                        "root ontology_keys must equal the concept ids bound by associations "
                        f"(associations bind {derived.get('ontology_keys')}, "
                        f"submitted {sorted(set(ontology_keys))})")
                for field in ("update_object", "mapping_status"):
                    expected = derived.get(field)
                    if expected is None:
                        continue
                    supplied = payload.get(field)
                    if supplied is None:
                        payload[field] = expected
                    elif supplied != expected:
                        raise ValueError(
                            f"root {field}={supplied!r} contradicts the association-derived "
                            f"value {expected!r}; root summaries derive from associations")
                roles = derived.get("research_roles") or []
                if roles:
                    supplied_roles = payload.get("research_roles")
                    supplied_role = payload.get("research_role")
                    if supplied_roles is not None:
                        if sorted({str(r) for r in supplied_roles}) != roles:
                            raise ValueError(
                                "root research_roles contradict the association-derived set "
                                f"{roles}")
                    elif supplied_role is not None and supplied_role not in roles:
                        raise ValueError(
                            f"root research_role={supplied_role!r} is not among the "
                            f"association-derived roles {roles}")
                    elif supplied_role is None and supplied_roles is None:
                        payload["research_roles"] = roles
            latest = conn.execute(
                "SELECT * FROM research_interpretations WHERE batch_id=? AND source_record_id=? ORDER BY version DESC LIMIT 1",
                (batch_id, source_record_id),
            ).fetchone()
            if expected_head_id is not None and (latest["id"] if latest else None) != expected_head_id:
                raise ValueError("expected_head_id does not match the current interpretation head")
            if latest and not supersedes_id:
                same = (
                    latest["schema_version"] == schema_version
                    and latest["ontology_version"] == ontology_version
                    and _row_value(latest, "release_id") == bound_release_id
                    and json.loads(latest["ontology_keys_json"] or "[]") == sorted(set(ontology_keys))
                    and json.loads(latest["payload_json"]) == payload
                    and _canonical_claims(self._record_claims(conn, "interpretation", latest["id"])) == _canonical_claims(claims)
                )
                if same:
                    if (latest["validity_status"] != "active" or
                            item["interpretation_id"] not in (None, latest["id"])):
                        raise ValueError("idempotent retry requires the current active interpretation head")
                    conn.execute(
                        """UPDATE research_batch_items SET status='submitted',interpretation_id=?,last_error=NULL,
                           worker_owner=NULL,started_at=NULL,heartbeat_at=NULL,lease_expires_at=NULL,updated_at=?
                           WHERE batch_id=? AND source_id=? AND source_record_id=?""",
                        (latest["id"], _now(), batch_id, record["source_id"],source_record_id),
                    )
                    self._reconcile_batch(conn, batch_id)
                    result = {
                        "interpretation_id": latest["id"], "version": latest["version"],
                        "validation_status": latest["validation_status"],
                        "agent_review_status": latest["agent_review_status"],
                        "human_adoption_status": latest["human_adoption_status"],
                        "validity_status": latest["validity_status"], "created": False,
                        "submission_mode": mode,
                        "release_id": _row_value(latest, "release_id"),
                    }
                    record_operation_effect(conn, result)
                    conn.commit()
                    return result
                raise ValueError("non-identical interpretation submission requires supersedes_id")
            if supersedes_id:
                old = conn.execute(
                    "SELECT * FROM research_interpretations WHERE id=? AND source_record_id=?",
                    (supersedes_id,source_record_id),
                ).fetchone()
                if not old:
                    raise KeyError(supersedes_id)
                if (not latest or supersedes_id != latest["id"] or
                        latest["validity_status"] != "active" or
                        item["interpretation_id"] != latest["id"]):
                    raise ValueError("supersedes_id must be the current active interpretation head")
            elif latest:
                raise ValueError("existing interpretation requires supersedes_id")
            version = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM research_interpretations WHERE batch_id=? AND source_record_id=?",
                (batch_id,source_record_id),
            ).fetchone()[0]
            iid, now = _id("RI"), _now()
            conn.execute(
                """INSERT INTO research_interpretations
                (id,batch_id,source_record_id,source_id,source_file_id,parse_run_id,snapshot_id,
                 snapshot_sha256,ontology_version,ontology_keys_json,schema_version,version,payload_json,
                 validation_status,agent_review_status,human_adoption_status,validity_status,
                 supersedes_id,layer,content_state,release_id,definition_refs_json,scope_json,feedback_id,
                 submitted_by,source_metadata_record_id,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'passed','pending','pending','active',?,
                        'interpretation','needs_review',?,?,?,?,?,?,?,?)""",
                (iid,batch_id,source_record_id,record["source_id"],source["source_file_id"],
                 snap["parse_run_id"],snap["id"],snap["content_sha256"],ontology_version,
                 json.dumps(sorted(set(ontology_keys)),ensure_ascii=False),schema_version,version,
                 json.dumps(payload,ensure_ascii=False),supersedes_id,
                 bound_release_id,definition_refs_json,
                 json.dumps(scope,ensure_ascii=False) if scope else None,feedback_id,
                 origin_submitter,pinned_metadata_id,now,now),
            )
            self._insert_claims(conn, layer="interpretation", record_id=iid, snapshot=snap, claims=claims)
            self._link_feedback_row(conn, feedback_id, iid, now)
            baseline_preserved = False
            if supersedes_id:
                predecessor = conn.execute(
                    "SELECT content_state,validity_status FROM research_interpretations WHERE id=?",
                    (supersedes_id,)).fetchone()
                if predecessor and predecessor["content_state"] == "stable" \
                        and predecessor["validity_status"] == "active":
                    # keep the old stable baseline usable while this candidate
                    # awaits independent review; switched on approval
                    baseline_preserved = True
                else:
                    conn.execute(
                        "UPDATE research_interpretations SET validity_status='superseded',updated_at=? WHERE id=?",
                        (now, supersedes_id),
                    )
            conn.execute(
                """UPDATE research_batch_items SET status='submitted',interpretation_id=?,last_error=NULL,
                   worker_owner=NULL,started_at=NULL,heartbeat_at=NULL,lease_expires_at=NULL,updated_at=?
                   WHERE batch_id=? AND source_id=? AND source_record_id=?""",
                (iid,now,batch_id,record["source_id"],source_record_id),
            )
            self._reconcile_batch(conn, batch_id)
            result = {"interpretation_id": iid, "version": version,
                      "validation_status": "passed", "agent_review_status": "pending",
                      "human_adoption_status": "pending", "validity_status": "active", "created": True,
                      "submission_mode": mode, "baseline_preserved": baseline_preserved,
                      "release_id": bound_release_id}
            record_operation_effect(conn, result)
            conn.commit()
            return result

    def _link_feedback_row(self, conn: sqlite3.Connection, feedback_id: str | None,
                           revision_id: str, now: str) -> None:
        """Close the feedback loop: a formal revision citing feedback_id links back."""
        if not feedback_id:
            return
        row = conn.execute("SELECT status FROM research_feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row:
            raise KeyError(feedback_id)
        if row["status"] == "closed":
            raise ValueError("feedback already closed")
        conn.execute(
            "UPDATE research_feedback SET formal_revision_id=?,status='formal_revision_created',updated_at=? WHERE id=?",
            (revision_id, now, feedback_id),
        )

    def _gate_stable_approval(self, conn: sqlite3.Connection, table: str, row: sqlite3.Row) -> None:
        """Approval to ``stable`` re-validates the payload against the record's
        own bound release definition (contract v5).

        - legacy structure (no release binding) can never be approved as-is:
          the content must be re-expressed under a released definition first;
        - a payload that no longer passes its bound definition (e.g. missing
          required fields) cannot become stable.
        """
        if not row["release_id"] or not row["definition_refs_json"]:
            raise ValueError(
                f"{row['id']} is on a legacy structure without a release binding; "
                "re-submit it under the released definition and review that record "
                "(migration never promotes legacy content to stable as-is)")
        refs = json.loads(row["definition_refs_json"])
        layer = "source_record" if table == "research_source_records" else "interpretation"
        ref = next(r for r in refs if r["layer"] == layer)
        definition = DefinitionService(self.context).get_definition(layer, ref["version"])
        payload = json.loads(row["payload_json"])
        validate_payload_against_definition(layer, payload, definition["payload"])

    def agent_review_source(self, record_id: str, *, decision: str, note: str = "",
                            actor_id: str | None = None) -> dict:
        if decision not in STATUSES["agent_review"]:
            raise ValueError("invalid agent review decision")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM research_source_records WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise KeyError(record_id)
            if decision == "approved":
                _require_reviewer_identity(decision, actor_id, row["submitted_by"],
                                           action="source agent review")
                if row["validation_status"] != "passed" or row["validity_status"] != "active":
                    raise ValueError("source approval requires passed validation and active validity")
                self._gate_stable_approval(conn, "research_source_records", row)
            now = _now()
            # needs_revision/rejected mean content deficiencies: the record goes
            # back to needs_completion, not to the review queue as if complete.
            content_state = "stable" if decision == "approved" else "needs_completion"
            conn.execute(
                """UPDATE research_source_records SET agent_review_status=?,content_state=?,
                   updated_at=? WHERE id=?""",
                (decision,content_state,now,record_id))
            if decision == "approved" and row["supersedes_id"]:
                # baseline switch happens at approval, not at submission: retire
                # still-active predecessors and stale their interpretations now
                conn.execute(
                    """UPDATE research_source_records SET validity_status='superseded',updated_at=?
                       WHERE batch_id=? AND source_id=? AND version<? AND validity_status='active'""",
                    (now, row["batch_id"], row["source_id"], row["version"]))
                # U8/U19/U24: compare actual normalized claims/evidence and
                # scoped extensions, then propagate only along D.input_refs.
                semantic_units, locator_units, unknown_semantic = _source_revision_changes(
                    conn, row["supersedes_id"], record_id)
                dependents = conn.execute(
                    """SELECT id,scope_json FROM research_interpretations
                       WHERE source_record_id IN (
                           SELECT id FROM research_source_records
                           WHERE batch_id=? AND source_id=? AND version<?)
                         AND validity_status='active'""",
                    (row["batch_id"], row["source_id"], row["version"])).fetchall()
                for dependent in dependents:
                    try:
                        refs = set((json.loads(dependent["scope_json"] or "{}") or {})
                                   .get("input_refs") or [])
                    except (TypeError, ValueError):
                        refs = set()
                    semantic_hit = unknown_semantic or not refs or bool(refs & semantic_units)
                    locator_hit = bool(refs & locator_units)
                    kind = "semantic" if semantic_hit else (
                        "locator" if locator_hit else "unrelated")
                    impacted = sorted(refs & (semantic_units | locator_units))
                    conn.execute(
                        """INSERT OR REPLACE INTO research_source_impacts
                           (new_source_record_id,prior_source_record_id,interpretation_id,
                            impacted_unit_keys_json,change_kind,requires_rereview,created_at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (record_id, row["supersedes_id"], dependent["id"],
                         json.dumps(impacted, ensure_ascii=False), kind,
                         int(semantic_hit or locator_hit), now))
                    if semantic_hit:
                        conn.execute(
                            "UPDATE research_interpretations SET validity_status='stale',updated_at=? WHERE id=?",
                            (now, dependent["id"]))
            conn.execute("INSERT INTO research_review_events(id,record_layer,record_id,actor_type,actor_id,decision,note,created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (_id("RR"),"source_record",record_id,"agent",actor_id,decision,note,now))
            conn.commit()
            return {"record_id":record_id,"validation_status":row["validation_status"],
                    "agent_review_status":decision,"human_adoption_status":row["human_adoption_status"],
                    "content_state":content_state,
                    "validity_status":row["validity_status"]}

    def human_adopt_source(self, record_id: str, *, decision: str, note: str = "",
                           scope: dict | None = None, actor_id: str | None = None) -> dict:
        if decision not in STATUSES["human_adoption"] or decision == "pending":
            raise ValueError("human decision must be adopted or rejected")
        _require_reviewer_identity(decision, actor_id, action="source human adoption")
        with closing(self._write_conn()) as conn:
            row = conn.execute("SELECT * FROM research_source_records WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise KeyError(record_id)
            if decision == "adopted" and not (row["validation_status"] == "passed" and
                    row["agent_review_status"] == "approved" and row["validity_status"] == "active"):
                raise ValueError("source adoption requires passed, active, agent-approved source record")
            if decision == "adopted" and _row_value(row, "content_state") not in (None, "stable"):
                raise ValueError("source adoption requires stable content")
            now = _now()
            # B6: adoption scope is a first-class fact (see human_adopt)
            conn.execute("""UPDATE research_source_records SET human_adoption_status=?,
                human_adoption_scope_json=?,updated_at=? WHERE id=?""",
                (decision,
                 json.dumps(scope, ensure_ascii=False) if scope is not None else None,
                 now, record_id))
            conn.execute("""INSERT INTO research_review_events
                (id,record_layer,record_id,actor_type,actor_id,decision,scope_json,note,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (_id("RR"),"source_record",record_id,"human",actor_id,decision,
                 json.dumps(scope,ensure_ascii=False) if scope is not None else None,note,now))
            conn.commit()
            return {"record_id":record_id,"validation_status":row["validation_status"],
                    "agent_review_status":row["agent_review_status"],"human_adoption_status":decision,
                    "content_state":_row_value(row, "content_state"),
                    "validity_status":row["validity_status"], "scope": scope,
                    "actor_type": "human", "actor_id": actor_id}

    def agent_review(self, interpretation_id: str, *, decision: str, note: str = "",
                     proposal_id: str | None = None, actor_id: str | None = None) -> dict:
        if decision not in STATUSES["agent_review"]:
            raise ValueError("invalid agent review decision")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM research_interpretations WHERE id=?", (interpretation_id,)).fetchone()
            if not row:
                raise KeyError(interpretation_id)
            if decision == "approved":
                _require_reviewer_identity(decision, actor_id, row["submitted_by"],
                                           action="interpretation agent review")
                if row["validation_status"] != "passed" or row["validity_status"] != "active":
                    raise ValueError("interpretation approval requires passed validation and active validity")
                self._gate_stable_approval(conn, "research_interpretations", row)
                # PLATFORM-004: the recommendation gate is shared across
                # layers — a D may only be approved onto the baseline when the
                # C it pins is itself an approved, active, stable record and
                # the A dependency is compatible (missing pins fail closed).
                pinned_c = conn.execute(
                    "SELECT * FROM research_source_records WHERE id=?", (row["source_record_id"],)
                ).fetchone()
                if not pinned_c or pinned_c["validity_status"] != "active" or \
                        pinned_c["agent_review_status"] != "approved" or \
                        _row_value(pinned_c, "content_state") != "stable":
                    state = (f"{pinned_c['validity_status']}/{pinned_c['agent_review_status']}/"
                             f"{_row_value(pinned_c, 'content_state')}" if pinned_c else "missing")
                    raise ValueError(
                        "interpretation approval requires the pinned source record to be an "
                        f"active approved stable C; pinned C state: {state}")
                source_work = conn.execute(
                    "SELECT work_id FROM research_sources WHERE id=?", (row["source_id"],)
                ).fetchone()
                metadata_dependency = assess_metadata_dependency(
                    conn, work_id=source_work["work_id"],
                    pinned_record_id=_row_value(row, "source_metadata_record_id"))
                if not metadata_dependency["usable"]:
                    raise ValueError(
                        "interpretation approval requires a compatible approved metadata "
                        f"dependency: {metadata_dependency.get('reason') or metadata_dependency['status']}")
            proposal = None
            if proposal_id:
                proposal = conn.execute(
                    "SELECT * FROM research_ontology_proposals WHERE id=?", (proposal_id,)
                ).fetchone()
                if not proposal:
                    raise KeyError(proposal_id)
                if proposal["status"] != "pilot_published":
                    raise ValueError("proposal-specific review requires a pilot-published ontology")
                impact = conn.execute(
                    "SELECT 1 FROM research_ontology_impacts WHERE proposal_id=? AND interpretation_id=?",
                    (proposal_id, interpretation_id),
                ).fetchone()
                if (row["ontology_version"] != proposal["proposed_version"] or
                        not row["supersedes_id"] or not impact):
                    raise ValueError("proposal-specific review must target its new relabel revision")
            now = _now()
            content_state = "stable" if decision == "approved" else "needs_completion"
            conn.execute(
                """UPDATE research_interpretations SET agent_review_status=?,content_state=?,
                   updated_at=? WHERE id=?""",
                (decision,content_state,now,interpretation_id))
            if decision == "approved" and row["supersedes_id"]:
                # baseline switch at approval: retire still-active predecessors
                conn.execute(
                    """UPDATE research_interpretations SET validity_status='superseded',updated_at=?
                       WHERE batch_id=? AND source_record_id=? AND version<? AND validity_status='active'""",
                    (now, row["batch_id"], row["source_record_id"], row["version"]))
            if proposal_id:
                conn.execute(
                    """UPDATE research_ontology_impacts SET requires_rereview=?
                       WHERE proposal_id=? AND interpretation_id IN (?,?)""",
                    (0 if decision == "approved" else 1,
                     proposal_id, interpretation_id, row["supersedes_id"]),
                )
            conn.execute("""INSERT INTO research_review_events
                (id,record_layer,record_id,ontology_proposal_id,actor_type,actor_id,decision,note,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (_id("RR"),"interpretation",interpretation_id,proposal_id,"agent",actor_id,decision,note,now))
            conn.commit()
            return {"interpretation_id": interpretation_id, "validation_status":row["validation_status"],
                    "agent_review_status": decision,"human_adoption_status": row["human_adoption_status"],
                    "content_state": content_state,
                    "validity_status":row["validity_status"], "ontology_proposal_id": proposal_id,
                    "actor_type": "agent", "actor_id": actor_id}

    def human_adopt(self, interpretation_id: str, *, decision: str, note: str = "",
                    scope: dict | None = None, actor_id: str | None = None) -> dict:
        if decision not in STATUSES["human_adoption"] or decision == "pending":
            raise ValueError("human decision must be adopted or rejected")
        _require_reviewer_identity(decision, actor_id, action="human adoption")
        with closing(self._write_conn()) as conn:
            row = conn.execute("""SELECT i.*,r.validity_status AS source_validity_status
                FROM research_interpretations i JOIN research_source_records r ON r.id=i.source_record_id
                WHERE i.id=?""", (interpretation_id,)).fetchone()
            if not row:
                raise KeyError(interpretation_id)
            if decision == "adopted" and row["agent_review_status"] != "approved":
                raise ValueError("human adoption requires agent-approved interpretation")
            if decision == "adopted" and row["validity_status"] != "active":
                raise ValueError("stale interpretation must be re-reviewed before adoption")
            if decision == "adopted" and row["validation_status"] != "passed":
                raise ValueError("interpretation adoption requires passed validation")
            if decision == "adopted" and _row_value(row, "content_state") not in (None, "stable"):
                raise ValueError("interpretation adoption requires stable content")
            if decision == "adopted" and row["source_validity_status"] != "active":
                raise ValueError("interpretation adoption requires an active source record")
            if decision == "adopted" and conn.execute(
                """SELECT 1 FROM research_ontology_impacts
                   WHERE interpretation_id=? AND requires_rereview=1 LIMIT 1""",
                (interpretation_id,),
            ).fetchone():
                raise ValueError("interpretation adoption requires proposal-specific ontology re-review approval")
            now = _now()
            # B6: adoption scope is a first-class fact — a scoped decision keeps
            # the record's adoption status but persists WHAT it covers, so
            # consumption judges per scope instead of over-reading one event.
            conn.execute("""UPDATE research_interpretations SET human_adoption_status=?,
                human_adoption_scope_json=?,updated_at=? WHERE id=?""",
                (decision,
                 json.dumps(scope, ensure_ascii=False) if scope is not None else None,
                 now, interpretation_id))
            conn.execute("""INSERT INTO research_review_events
                (id,record_layer,record_id,actor_type,actor_id,decision,scope_json,note,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (_id("RR"),"interpretation",interpretation_id,"human",actor_id,decision,
                 json.dumps(scope,ensure_ascii=False) if scope is not None else None,note,now))
            conn.commit()
            return {"interpretation_id": interpretation_id, "validation_status":row["validation_status"],
                    "agent_review_status": row["agent_review_status"],"human_adoption_status": decision,
                    "content_state":_row_value(row, "content_state"),
                    "validity_status":row["validity_status"], "scope": scope,
                    "actor_type": "human", "actor_id": actor_id}

    def evidence(self, *, record_id: str | None = None, claim_key: str | None = None) -> list[dict]:
        where, params = [], []
        if record_id:
            where.append("c.record_id=?"); params.append(record_id)
        if claim_key:
            where.append("c.claim_key=?"); params.append(claim_key)
        clause = " WHERE " + " AND ".join(where) if where else ""
        with closing(self.context.connect(read_only=True)) as conn:
            rows = conn.execute(
                """SELECT c.record_layer,c.record_id,c.claim_key,c.claim_text,
                          e.snapshot_id,e.quote,e.start_offset,e.end_offset,e.locator_json
                   FROM research_claims c JOIN research_evidence e ON e.claim_id=c.id""" + clause +
                " ORDER BY c.record_id,c.claim_key,e.start_offset", params,
            ).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                # U19 preview: the quote never travels alone — the bound
                # snapshot supplies its immediate context and which occurrence
                # of repeated text this anchor pins, so a reviewer can act on
                # the locator instead of reading raw parameters.
                snap = conn.execute(
                    """SELECT content_text,version,page_count,page_sizes,page_offsets
                       FROM research_text_snapshots WHERE id=?""",
                    (item["snapshot_id"],)).fetchone()
                if snap:
                    content = snap["content_text"] or ""
                    start = item["start_offset"] or 0
                    end = item["end_offset"] if item["end_offset"] is not None else start
                    window = 120
                    item["context_before"] = content[max(0, start - window):start]
                    item["context_after"] = content[end:end + window]
                    item["snapshot_version"] = snap["version"]
                    item["locator_verification"] = {
                        "page_count_declared": snap["page_count"] is not None,
                        "page_geometry_declared": bool(snap["page_sizes"]),
                        "page_text_correspondence": "exact" if snap["page_offsets"] else "not_verified",
                        "region_preview": "coordinates_only",
                    }
                    total = content.count(item["quote"]) if item["quote"] else 0
                    item["quote_occurrence"] = (
                        {"index": content[:start].count(item["quote"]) + 1, "total": total}
                        if total > 1 else None)
                results.append(item)
            return results

    def source_record_impact(self, record_id: str) -> dict:
        """Return persisted local C→D impact decisions for one C revision."""
        with closing(self.context.connect(read_only=True)) as conn:
            if not conn.execute("SELECT 1 FROM research_source_records WHERE id=?",
                                (record_id,)).fetchone():
                raise KeyError(record_id)
            rows = []
            for row in conn.execute(
                    """SELECT prior_source_record_id,interpretation_id,
                              impacted_unit_keys_json,change_kind,requires_rereview,created_at
                       FROM research_source_impacts WHERE new_source_record_id=?
                       ORDER BY interpretation_id,change_kind""", (record_id,)):
                item = dict(row)
                item["impacted_unit_keys"] = json.loads(
                    item.pop("impacted_unit_keys_json") or "[]")
                item["requires_rereview"] = bool(item["requires_rereview"])
                rows.append(item)
        return {"source_record_id": record_id, "items": rows}

    def effective_interpretations(self, batch_id: str) -> list[dict]:
        """Usable-basis view (contract v5): stable content only.

        ``stable`` means passed structural validation plus independent agent
        review approval on both the source record and the interpretation.
        Human adoption is an overlay judgment and is deliberately NOT part of
        this gate (R04/R07/U3): unread or human-pending materials keep
        participating in research consumption.  On a pre-conversion (v4) store
        the content_state predicate is dropped instead of failing with 500.
        """
        basis = self.usable_basis(batch_id)
        ids = [item["interpretation_id"] for item in basis["items"]
               if item["usable"] and item["interpretation_id"]]
        if not ids:
            return []
        with closing(self.context.connect(read_only=True)) as conn:
            marks = ",".join("?" for _ in ids)
            return [dict(r) for r in conn.execute(
                f"SELECT * FROM research_interpretations WHERE id IN ({marks}) "
                "ORDER BY source_id,version", ids)]

    def usable_basis(self, batch_id: str) -> dict:
        """Per-work usable basis vs current revision, with content three-states.

        Contract v5 (controller counterexample: usable 1→0 on candidate): the
        usable basis follows the latest *stable baseline* per (batch, source),
        not the batch-item binding — submitting a candidate never withdraws the
        previously approved baseline because supersession happens at approval.
        Pending candidates are reported alongside as ``pending_*`` entries.
        """
        with closing(self.context.connect(read_only=True)) as conn:
            if not conn.execute("SELECT 1 FROM research_batches WHERE id=?", (batch_id,)).fetchone():
                raise KeyError(batch_id)
            v5 = research_v5_available(conn)
            stable_src = "AND r.content_state='stable'" if v5 else ""
            stable_int = "AND i.content_state='stable'" if v5 else ""
            rows = conn.execute(
                f"""SELECT s.id AS source_id, s.work_id, s.citation_key,
                       r.id AS source_record_id, r.version AS source_record_version,
                       r.validity_status AS source_validity_status,
                       r.agent_review_status AS source_agent_review_status,
                       r.human_adoption_status AS source_human_adoption_status,
                       {_c(v5, "r.content_state")} AS source_content_state,
                       i.id AS interpretation_id, i.version AS interpretation_version,
                       i.validity_status AS interpretation_validity_status,
                       i.agent_review_status AS interpretation_agent_review_status,
                       i.human_adoption_status AS interpretation_human_adoption_status,
                       {_c(v5, "i.content_state")} AS interpretation_content_state,
                       i.ontology_version
                FROM research_sources s
                JOIN research_batch_items bi ON bi.source_id=s.id AND bi.batch_id=?
                LEFT JOIN research_source_records r ON r.batch_id=bi.batch_id AND r.source_id=s.id
                     AND r.validity_status='active' AND r.validation_status='passed'
                     AND r.agent_review_status='approved' {stable_src}
                     AND r.version=(SELECT MAX(r2.version) FROM research_source_records r2
                                    WHERE r2.batch_id=r.batch_id AND r2.source_id=r.source_id
                                    AND r2.validity_status='active' AND r2.validation_status='passed'
                                    AND r2.agent_review_status='approved' {stable_src})
                LEFT JOIN research_interpretations i ON i.batch_id=bi.batch_id
                     AND i.source_record_id=r.id
                     AND i.validity_status='active' AND i.validation_status='passed'
                     AND i.agent_review_status='approved' {stable_int}
                     AND i.version=(SELECT MAX(i2.version) FROM research_interpretations i2
                                    WHERE i2.batch_id=i.batch_id AND i2.source_record_id=i.source_record_id
                                    AND i2.validity_status='active' AND i2.validation_status='passed'
                                    AND i2.agent_review_status='approved' {stable_int})
                ORDER BY s.work_id, s.id""", (batch_id,)
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                dependency_pending: list[dict] = []
                # R8: D stays pinned to the C version it actually interpreted.
                # Resolve compatibility through the current C lineage instead
                # of requiring an identity join to the current head.
                if item["source_record_id"]:
                    compatible, dependency_pending = _compatible_interpretation(
                        conn, batch_id=batch_id, source_id=item["source_id"],
                        head_id=item["source_record_id"], v5=v5)
                    if compatible:
                        item.update({
                            "interpretation_id": compatible["id"],
                            "interpretation_version": compatible["version"],
                            "interpretation_validity_status": compatible["validity_status"],
                            "interpretation_agent_review_status": compatible["agent_review_status"],
                            "interpretation_human_adoption_status": compatible["human_adoption_status"],
                            "interpretation_content_state": _row_value(
                                compatible, "content_state"),
                            "ontology_version": compatible["ontology_version"],
                            "interpretation_source_record_id": compatible["source_record_id"],
                        })
                # B6: usable follows the request scope — when the plan or the C
                # record's record_mode marks D not required, a C-only row is a
                # complete, consumable basis instead of a perpetually unusable one.
                int_required = True
                if not item["interpretation_id"]:
                    active_r = None
                    if item["source_record_id"]:
                        active_r = conn.execute(
                            "SELECT payload_json FROM research_source_records WHERE id=?",
                            (item["source_record_id"],)).fetchone()
                    int_required = not _interpretation_not_required(
                        conn, batch_id, item["source_id"], active_r)
                item["interpretation_required"] = int_required
                # B6: an explicitly requested unit scope is part of the
                # consumption contract — a stable record that does not cover
                # the requested units is NOT a usable fulfilment of the
                # request; it is flagged and excluded from usable.
                requested_units = ((_requested_scope_targets(conn, batch_id, item["source_id"]) or {})
                                   .get("scope") or {}).get("unit_keys") or []
                if requested_units:
                    delivered_refs: set = set()
                    # A local C-only commission is satisfied by C's units.
                    # A required D commission is satisfied by D's own scope,
                    # never by the union of C and D.
                    if item["source_record_id"] and not int_required:
                        sr_row2 = conn.execute(
                            "SELECT payload_json FROM research_source_records WHERE id=?",
                            (item["source_record_id"],)).fetchone()
                        if sr_row2:
                            try:
                                sr_units = json.loads(sr_row2["payload_json"]).get("units") or []
                                delivered_refs |= {
                                    str(u.get("unit_key")) for u in sr_units
                                    if isinstance(u, dict) and u.get("unit_key")}
                            except (TypeError, ValueError):
                                pass
                    if item["interpretation_id"]:
                        scope_row2 = conn.execute(
                            "SELECT scope_json FROM research_interpretations WHERE id=?",
                            (item["interpretation_id"],)).fetchone()
                        if scope_row2 and scope_row2["scope_json"]:
                            try:
                                delivered_refs |= set(
                                    (json.loads(scope_row2["scope_json"]) or {}).get("input_refs") or [])
                            except (TypeError, ValueError):
                                pass
                    item["requested_scope"] = sorted(requested_units)
                    item["requested_scope_met"] = requested_units and                         set(requested_units) <= delivered_refs
                item["usable"] = bool(item["source_record_id"] and
                                      (item["interpretation_id"] or not int_required) and
                                      item.get("requested_scope_met", True))
                if item.get("interpretation_id") and v5:
                    item["source_dependency_review_pending"] = dependency_pending
                item["waiting_human"] = bool(item["usable"] and (
                    item["source_human_adoption_status"] == "pending"
                    or item["interpretation_human_adoption_status"] == "pending"
                ))
                # B6: a scoped human adoption is surfaced as scoped — consumers
                # must see which part the human decision covers and that the
                # rest of the record is NOT human-endorsed.
                if v5:
                    scope_row = conn.execute(
                        """SELECT human_adoption_scope_json, id FROM research_interpretations
                           WHERE id=?""", (item["interpretation_id"],)).fetchone() \
                        if item["interpretation_id"] else None
                    if scope_row and scope_row["human_adoption_scope_json"]:
                        try:
                            item["interpretation_human_adoption_scope"] = json.loads(
                                scope_row["human_adoption_scope_json"])
                        except (TypeError, ValueError):
                            item["interpretation_human_adoption_scope"] = None
                    if item.get("interpretation_human_adoption_scope"):
                        item["human_adoption_coverage"] = {
                            "interpretation": "partial",
                            "scope": item["interpretation_human_adoption_scope"],
                            "note": "人工采纳仅覆盖声明范围；其余解释/单元内容未经人工认可",
                        }
                    pinned_metadata_id = None
                    if item["interpretation_id"]:
                        dep = conn.execute(
                            "SELECT source_metadata_record_id FROM research_interpretations WHERE id=?",
                            (item["interpretation_id"],)).fetchone()
                        pinned_metadata_id = dep["source_metadata_record_id"] if dep else None
                        metadata_dependency = assess_metadata_dependency(
                            conn, work_id=item["work_id"], pinned_record_id=pinned_metadata_id)
                        item["metadata_dependency"] = metadata_dependency
                        item["metadata_dependency_review_pending"] = not metadata_dependency["usable"]
                        item["usable"] = bool(item["usable"] and metadata_dependency["usable"])
                    else:
                        # C-only consumption does not depend on A (A is D's
                        # dependency).  The work's approved stable head is
                        # reported informationally so catalog quality stays
                        # visible, but it never gates a legitimate C-only item.
                        head = current_metadata_head(conn, item["work_id"],
                                                     approved_stable_only=True)
                        item["metadata_dependency"] = {
                            "status": "not_applicable",
                            "usable": True,
                            "gates_usable": False,
                            "work_head_record_id": head["id"] if head else None,
                            "reason": "C-only 消费不依赖 A；仅报告 work 的 approved stable A 头",
                        }
                        item["metadata_dependency_review_pending"] = False
                item["pending_source_candidates"] = [dict(p) for p in conn.execute(
                    f"""SELECT id, version, validation_status, agent_review_status,
                               {_c(v5, "content_state")} AS content_state
                        FROM research_source_records
                        WHERE batch_id=? AND source_id=? AND validity_status='active'
                          AND NOT (validation_status='passed' AND agent_review_status='approved'
                                   {stable_src.replace("r.", "")})""",
                    (batch_id, item["source_id"]),
                )]
                item["pending_interpretation_candidates"] = []
                # v4 stores lack source_metadata_record_id — degrade explicitly
                # instead of failing the whole basis query (A9 contract).
                pin_column = ",source_metadata_record_id" if v5 else ""
                for p in conn.execute(
                    f"""SELECT id, version, validation_status, agent_review_status{pin_column},
                               {_c(v5, "content_state")} AS content_state
                        FROM research_interpretations
                        WHERE batch_id=? AND source_id=? AND validity_status='active'
                          AND NOT (validation_status='passed' AND agent_review_status='approved'
                                   {stable_int.replace("i.", "")})""",
                    (batch_id, item["source_id"]),
                ):
                    candidate = dict(p)
                    # 漏 A 的待审 D 在候选行上直接可见其依赖状态——
                    # 不能既不进基线又无处暴露 A 钉定缺口。
                    if v5:
                        candidate["metadata_dependency"] = assess_metadata_dependency(
                            conn, work_id=item["work_id"],
                            pinned_record_id=candidate.get("source_metadata_record_id"))
                    else:
                        candidate["metadata_dependency"] = {
                            "status": "legacy_store", "usable": None,
                            "reason": "v4 存储无 A 层，依赖评估仅适用于 v5"}
                    item["pending_interpretation_candidates"].append(candidate)
                items.append(item)
            return {"batch_id": batch_id, "items": items,
                    "usable_count": sum(1 for item in items if item["usable"]),
                    "total": len(items),
                    "research_v5_available": v5,
                    "note": "usable=稳定基线（已结构校验并经独立审查批准）；候选待审不撤基线，"
                            "仅以 pending_* 列出；human pending 不阻断消费；"
                            "D 固定绑定其实际 C；当前 C 为该 C 的已分类直系后代且无 semantic"
                            "影响时可继续消费，locator 影响逐跳累计提示待复核；"
                            "计划或 record_mode 标明 D 不适用时 C-only 亦为完整可用范围"
                            "（interpretation_required=false）；"
                            "metadata_dependency 明确给出 D→A 固定依赖及字段影响；缺失、"
                            "身份冲突或影响解释范围的 A 变化会从推荐基线 fail closed",
                    "consumption_rules": {
                        "usable_gate": "C/D 两层稳定且批准",
                        "source_lineage": "固定绑定 D 仅沿当前 C 的完整 supersedes 谱系继承；"
                                          "缺失影响判定或 semantic 影响均阻断",
                        "metadata_review": "A 缺失/身份冲突/语义范围变化阻断推荐；"
                                           "仅展示或纯书目字段变化保留可用并记录差异",
                    }}

    def _record_claims(self, conn: sqlite3.Connection, layer: str, record_id: str | None) -> list[dict]:
        if not record_id:
            return []
        rows = conn.execute(
            """SELECT c.claim_key,c.claim_text,e.quote,e.start_offset,e.end_offset,e.locator_json
               FROM research_claims c JOIN research_evidence e ON e.claim_id=c.id
               WHERE c.record_layer=? AND c.record_id=?
               ORDER BY c.claim_key,e.start_offset""", (layer,record_id)
        ).fetchall()
        out: dict[str, dict] = {}
        for r in rows:
            item = out.setdefault(r["claim_key"], {"key": r["claim_key"], "text": r["claim_text"], "evidence": []})
            item["evidence"].append({"quote": r["quote"], "start_offset": r["start_offset"],
                                     "end_offset": r["end_offset"], "locator": json.loads(r["locator_json"] or "{}")})
        return list(out.values())

    def query(self, *, batch_id: str, q: str | None = None, source_id: str | None = None,
              work_id: str | None = None, citation_key: str | None = None,
              validation_status: str | None = None, mapping_status: str | None = None,
              update_object: str | None = None, research_role: str | None = None,
              deployment_condition: str | None = None,
              agent_review_status: str | None = None,
              human_adoption_status: str | None = None,
              source_validation_status: str | None = None,
              source_agent_review_status: str | None = None,
              source_human_adoption_status: str | None = None,
              source_validity_status: str | None = None,
              interpretation_validation_status: str | None = None,
              interpretation_agent_review_status: str | None = None,
              interpretation_human_adoption_status: str | None = None,
              interpretation_validity_status: str | None = None,
              source_content_state: str | None = None,
              interpretation_content_state: str | None = None,
              content_state: str | None = None,
              limit: int = 50) -> dict:
        """Explicit-batch projection; payload JSON is expanded and no latest row is inferred.

        Pre-conversion (v4) stores are read in degraded mode: content_state
        columns are projected as NULL and content_state filters are refused
        with an explicit message instead of a 500.
        """
        with closing(self.context.connect(read_only=True)) as conn:
            if not conn.execute("SELECT 1 FROM research_batches WHERE id=?", (batch_id,)).fetchone():
                raise KeyError(batch_id)
            v5 = research_v5_available(conn)
        where, params = ["bi.batch_id=?"], [batch_id]
        if source_id:
            where.append("s.id=?"); params.append(source_id)
        if work_id:
            where.append("s.work_id=?"); params.append(work_id)
        if citation_key:
            where.append("(s.citation_key=? OR EXISTS (SELECT 1 FROM research_source_citations c WHERE c.source_id=s.id AND c.key=?))")
            params.extend([citation_key,citation_key])
        # Compatibility aliases are intentionally interpretation-only.  They
        # never COALESCE source and interpretation state into one value.
        for alias_name, alias_value, explicit_name, explicit_value in (
            ("validation_status", validation_status, "interpretation_validation_status", interpretation_validation_status),
            ("agent_review_status", agent_review_status, "interpretation_agent_review_status", interpretation_agent_review_status),
            ("human_adoption_status", human_adoption_status, "interpretation_human_adoption_status", interpretation_human_adoption_status),
        ):
            if alias_value and explicit_value and alias_value != explicit_value:
                raise ValueError(f"conflicting {alias_name} and {explicit_name}")
        interpretation_validation_status = interpretation_validation_status or validation_status
        interpretation_agent_review_status = interpretation_agent_review_status or agent_review_status
        interpretation_human_adoption_status = interpretation_human_adoption_status or human_adoption_status
        if content_state and interpretation_content_state and content_state != interpretation_content_state:
            raise ValueError("conflicting content_state and interpretation_content_state")
        interpretation_content_state = interpretation_content_state or content_state
        if not v5 and (source_content_state or interpretation_content_state):
            raise ValueError(
                "research store is pre-conversion (v4): content_state filters require "
                "apply_schema conversion first")
        # Source filters describe the batch pointer that is displayed.  In
        # contrast, interpretation filters must wait until the effective D is
        # selected below: the batch pointer can be empty while a fixed older D
        # remains compatible with the current C lineage.
        state_filters = [
            ("r.validation_status", source_validation_status),
            ("r.agent_review_status", source_agent_review_status),
            ("r.human_adoption_status", source_human_adoption_status),
            ("r.validity_status", source_validity_status),
        ]
        if v5:
            state_filters += [("r.content_state", source_content_state)]
        for column, value in state_filters:
            if value:
                where.append(f"{column}=?")
                params.append(value)
        if q:
            literal = q.replace("%", "\\%").replace("_", "\\_")
            like = f"%{literal}%"
            where.append("(s.work_id LIKE ? ESCAPE '\\' OR COALESCE(s.citation_key,'') LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM research_source_citations c WHERE c.source_id=s.id AND c.key LIKE ? ESCAPE '\\') OR t.content_text LIKE ? ESCAPE '\\')")
            params.extend([like,like,like,like])
        from_sql = """ FROM research_batch_items bi JOIN research_sources s ON s.id=bi.source_id
                 JOIN research_text_snapshots t ON t.id=bi.snapshot_id
                 LEFT JOIN research_source_records r ON r.id=bi.source_record_id
                 LEFT JOIN research_interpretations i ON i.id=bi.interpretation_id
                 WHERE """ + " AND ".join(where)
        sql = f"""SELECT s.*,t.id AS t_id,t.version AS t_version,t.content_sha256 AS t_sha,
                        t.parse_run_id AS t_parse_run_id,t.parse_exists AS t_parse_exists,
                        t.parse_quality AS t_parse_quality,
                        bi.source_record_id,bi.interpretation_id,
                        r.version AS r_version,r.schema_version AS r_schema,r.payload_json AS r_payload,
                        r.validation_status AS r_validation_status,
                        r.agent_review_status AS r_agent_review_status,
                        r.human_adoption_status AS r_human_adoption_status,
                        r.validity_status AS r_validity_status,
                        {_c(v5, "r.content_state")} AS r_content_state,
                        i.version AS i_version,i.schema_version AS i_schema,i.ontology_version,
                        i.source_record_id AS i_source_record_id,
                        i.ontology_keys_json,i.payload_json AS i_payload,
                        i.validation_status AS i_validation_status,i.agent_review_status,
                        i.human_adoption_status,i.validity_status,
                        {_c(v5, "i.content_state")} AS i_content_state,
                        {_c(v5, "i.human_adoption_scope_json")} AS i_human_adoption_scope_json,
                        {_c(v5, "i.submitted_by")} AS i_submitted_by,
                        {_c(v5, "r.submitted_by")} AS r_submitted_by
                 """ + from_sql + " ORDER BY s.work_id,s.source_file_id,s.id"
        with closing(self.context.connect(read_only=True)) as conn:
            rows = conn.execute(sql,params).fetchall()
            items = []
            for r in rows:
                source = {k:r[k] for k in ("id","work_id","source_file_id","citation_key","source_path",
                          "snapshot_path","source_sha256")}
                source["parse_run_id"] = r["t_parse_run_id"]
                source["parse_exists"] = bool(r["t_parse_exists"])
                source["parse_quality"] = r["t_parse_quality"]
                source["citation_keys"] = [x[0] for x in conn.execute(
                    "SELECT key FROM research_source_citations WHERE source_id=? ORDER BY kind DESC,key", (r["id"],)
                )]
                source_record = None
                if r["source_record_id"]:
                    source_record = {"id":r["source_record_id"],"version":r["r_version"],
                                     "schema_version":r["r_schema"],"payload":json.loads(r["r_payload"]),
                                     "validation_status":r["r_validation_status"],
                                     "agent_review_status":r["r_agent_review_status"],
                                     "human_adoption_status":r["r_human_adoption_status"],
                                     "submitted_by":r["r_submitted_by"],
                                     "validity_status":r["r_validity_status"],
                                     "content_state":r["r_content_state"],
                                     "claims":self._record_claims(conn,"source_record",r["source_record_id"])}
                interpretation = None
                if r["interpretation_id"]:
                    interpretation = {"id":r["interpretation_id"],"version":r["i_version"],
                        "source_record_id":r["i_source_record_id"],
                        "schema_version":r["i_schema"],"ontology_version":r["ontology_version"],
                        "ontology_keys":json.loads(r["ontology_keys_json"] or "[]"),
                        "payload":json.loads(r["i_payload"]),"validation_status":r["i_validation_status"],
                        "agent_review_status":r["agent_review_status"],
                        "human_adoption_status":r["human_adoption_status"],"validity_status":r["validity_status"],
                        "content_state":r["i_content_state"],
                        # B6/B9: the human adoption scope and the generation
                        # origin travel with the projection so list/detail show
                        # the PARTIAL scope and the record's submitter.
                        "human_adoption_scope":json.loads(r["i_human_adoption_scope_json"] or "null")
                        if r["i_human_adoption_scope_json"] else None,
                        "submitted_by":r["i_submitted_by"],
                        "claims":self._record_claims(conn,"interpretation",r["interpretation_id"])}
                all_claims = (source_record or {}).get("claims",[]) + (interpretation or {}).get("claims",[])
                payload = (interpretation or {}).get("payload",{})
                items.append({"source":source,"snapshot":{"id":r["t_id"],"version":r["t_version"],
                    "content_sha256":r["t_sha"],"parse_run_id":r["t_parse_run_id"],
                    "parse_exists":bool(r["t_parse_exists"]),"parse_quality":r["t_parse_quality"]},
                    "source_record":source_record,"interpretation":interpretation,
                    "validation_status":((interpretation or {}).get("validation_status")),
                    "mapping_status":payload.get("mapping_status") if isinstance(payload,dict) else None,
                    "coverage":{"claims":len(all_claims),"evidence_anchors":sum(len(c["evidence"]) for c in all_claims)},
                    "unresolved":payload.get("unresolved",[]) if isinstance(payload,dict) else []})
            # B7: the query projection and the default exports must speak the
            # same language about which revision is the selected effective
            # baseline — the batch-item pointer may be a pending candidate.
            try:
                basis_items = self.usable_basis(batch_id)["items"]
            except (KeyError, ValueError):
                basis_items = []
            basis_by_source = {b["source_id"]: b for b in basis_items}
            # The list/detail projection consumes the same selected baseline as
            # exports.  The batch pointer can legitimately have no D after a C
            # revision, while the fixed older D remains lineage-compatible.
            for item in items:
                basis = basis_by_source.get(item["source"]["id"])
                if not basis:
                    continue
                item["source_dependency_review_pending"] = list(
                    basis.get("source_dependency_review_pending") or [])
                selected_id = basis.get("interpretation_id") if basis.get("usable") else None
                # Do not splice the approved D baseline into a pending C
                # candidate shown by the explicit batch pointer.
                if (not selected_id or not item.get("source_record") or
                        item["source_record"].get("id") != basis.get("source_record_id")):
                    continue
                selected = conn.execute(
                    "SELECT * FROM research_interpretations WHERE id=?", (selected_id,)
                ).fetchone()
                if selected:
                    selected = dict(selected)
                    item["interpretation"] = {
                        "id": selected["id"], "version": selected["version"],
                        "source_record_id": selected["source_record_id"],
                        "schema_version": selected["schema_version"],
                        "ontology_version": selected["ontology_version"],
                        "ontology_keys": json.loads(selected["ontology_keys_json"] or "[]"),
                        "payload": json.loads(selected["payload_json"]),
                        "validation_status": selected["validation_status"],
                        "agent_review_status": selected["agent_review_status"],
                        "human_adoption_status": selected["human_adoption_status"],
                        "validity_status": selected["validity_status"],
                        "content_state": selected.get("content_state"),
                        "human_adoption_scope": json.loads(
                            selected.get("human_adoption_scope_json") or "null"),
                        "submitted_by": selected.get("submitted_by"),
                        "claims": self._record_claims(conn, "interpretation", selected_id),
                    }
                    payload = item["interpretation"]["payload"]
                    item["validation_status"] = selected["validation_status"]
                    item["mapping_status"] = payload.get("mapping_status") \
                        if isinstance(payload, dict) else None
            # RWEB-01: surface the catalog title (library DB works table) on
            # every query item so remote lists never fall back to the virtual
            # asset URI's trailing version segment as a display name.
            from .db import DB_PATH as _library_db_path
            work_ids = sorted({item["source"]["work_id"] for item in items
                               if item["source"].get("work_id")})
            catalog_titles = {}
            if work_ids and _library_db_path.is_file():
                try:
                    lib = sqlite3.connect(f"file:{_library_db_path.as_posix()}?mode=ro", uri=True)
                    try:
                        placeholders = ",".join("?" * len(work_ids))
                        catalog_titles = {row[0]: row[1] for row in lib.execute(
                            f"SELECT id,title FROM works WHERE id IN ({placeholders})", work_ids)}
                    finally:
                        lib.close()
                except sqlite3.Error:
                    catalog_titles = {}
            for item in items:
                item["title"] = catalog_titles.get(item["source"].get("work_id"))
            # RWEB-02 (review P2): give research work orders the same fixed-version
            # asset locators as the metadata worklist - pdf binds to the source
            # file identity, md/json to the parse-run identity; the newest
            # registered version wins, never a guess.
            asset_ids = sorted({item["source"]["id"] for item in items} |
                               {item["snapshot"]["parse_run_id"] for item in items
                                if item["snapshot"].get("parse_run_id")} |
                               {item["source"]["source_file_id"] for item in items
                                if item["source"].get("source_file_id")})
            worklist_assets = {}
            if asset_ids:
                library_db = _library_db_path
                try:
                    lib = sqlite3.connect(f"file:{library_db.as_posix()}?mode=ro", uri=True)
                    try:
                        placeholders = ",".join("?" * len(asset_ids))
                        for binding in lib.execute(
                                f"SELECT identity,role,version,sha256,bytes FROM storage_bindings "
                                f"WHERE identity IN ({placeholders}) AND role IN ('pdf','md','json') "
                                f"ORDER BY identity,role,version DESC", asset_ids):
                            worklist_assets.setdefault(binding[0], {}).setdefault(binding[1], {
                                "identity": binding[0], "role": binding[1], "version": binding[2],
                                "sha256": binding[3], "bytes": binding[4]})
                    finally:
                        lib.close()
                except sqlite3.Error:
                    worklist_assets = {}
            for item in items:
                parse_run = item["snapshot"].get("parse_run_id")
                source_file = item["source"].get("source_file_id")
                item["assets"] = {"pdf": worklist_assets.get(source_file, {}).get("pdf"),
                                  "md": worklist_assets.get(parse_run, {}).get("md"),
                                  "json": worklist_assets.get(parse_run, {}).get("json")}
            # All derived fields and every interpretation-side filter consume
            # the same final D object selected above.  Filtering before this
            # point would silently test the batch pointer instead.
            def matches(actual, expected):
                if not expected:
                    return True
                if isinstance(actual, list):
                    return str(expected) in {str(value) for value in actual}
                return str(actual) == str(expected)

            interpretation_filters = (
                ("validation_status", interpretation_validation_status),
                ("agent_review_status", interpretation_agent_review_status),
                ("human_adoption_status", interpretation_human_adoption_status),
                ("validity_status", interpretation_validity_status),
                ("content_state", interpretation_content_state),
            )
            payload_filters = (
                ("mapping_status", mapping_status),
                ("update_object", update_object),
                ("research_role", research_role),
                ("deployment_condition", deployment_condition),
            )
            filtered_items = []
            for item in items:
                interpretation = item.get("interpretation") or {}
                payload = interpretation.get("payload") or {}
                all_claims = (item.get("source_record") or {}).get("claims", []) + \
                    interpretation.get("claims", [])
                item["validation_status"] = interpretation.get("validation_status")
                item["mapping_status"] = payload.get("mapping_status") \
                    if isinstance(payload, dict) else None
                item["coverage"] = {
                    "claims": len(all_claims),
                    "evidence_anchors": sum(len(claim["evidence"]) for claim in all_claims),
                }
                item["unresolved"] = payload.get("unresolved", []) \
                    if isinstance(payload, dict) else []
                if not all(matches(interpretation.get(key), value)
                           for key, value in interpretation_filters):
                    continue
                if not all(matches(payload.get(key), value)
                           for key, value in payload_filters):
                    continue
                filtered_items.append(item)
            total = len(filtered_items)
            items = filtered_items[:limit]
            baseline_int_ids = {b["interpretation_id"] for b in basis_items
                                if b["usable"] and b["interpretation_id"]}
            baseline_src_ids = {b["source_record_id"] for b in basis_items
                                if b["usable"] and b["source_record_id"]}
            for item in items:
                interpretation = item["interpretation"] or {}
                source_record = item["source_record"] or {}
                item["interpretation_in_usable_basis"] = bool(
                    interpretation and interpretation.get("id") in baseline_int_ids)
                item["source_record_in_usable_basis"] = bool(
                    source_record and source_record.get("id") in baseline_src_ids)
            return {"batch_id":batch_id,"total":total,"returned_count":len(items),"items":items,
                    "research_v5_available": v5,
                    "basis_rule": "interpretation_in_usable_basis / source_record_in_usable_basis "
                                  "标记已选有效基线；批项指针可能指向待审候选，不因指针而成为基线",
                    "compatibility_aliases":{
                        "validation_status":"interpretation_validation_status",
                        "agent_review_status":"interpretation_agent_review_status",
                        "human_adoption_status":"interpretation_human_adoption_status",
                    }}

    def work_view(self, work_id: str, *, batch_id: str) -> dict:
        result = self.query(batch_id=batch_id, work_id=work_id, limit=200)
        if not result["items"]:
            raise KeyError(work_id)
        return {"batch_id":batch_id,"work_id":work_id,"items":result["items"],
                "research_v5_available": result["research_v5_available"]}

    # ----- ontology proposal / impact / pilot publish / partial re-review -----
    def propose_ontology(self, *, base_version: str, proposed_version: str,
                         changed_keys: list[str], payload: dict) -> dict:
        with closing(self._write_conn()) as conn:
            base = conn.execute("SELECT payload_json FROM research_ontology_versions WHERE version=?", (base_version,)).fetchone()
            if not base:
                raise KeyError(base_version)
            changed = sorted(set(changed_keys))
            if not changed:
                raise ValueError("changed_keys must identify at least one concept")
            known = _concept_ids(json.loads(base["payload_json"])) | _concept_ids(payload)
            unknown = sorted(set(changed) - known)
            if unknown:
                raise ValueError(f"changed_keys are not verifiable concept ids: {unknown}")
            if payload.get("version") and payload["version"] != proposed_version:
                raise ValueError("ontology payload version does not match proposed_version")
            pid, now = _id("ROP"), _now()
            conn.execute(
                """INSERT INTO research_ontology_proposals
                (id,base_version,proposed_version,changed_keys_json,payload_json,status,created_at,updated_at)
                VALUES (?,?,?,?,?,'proposed',?,?)""",
                (pid,base_version,proposed_version,json.dumps(changed),
                 json.dumps(payload,ensure_ascii=False),now,now),
            )
            conn.commit()
            return {"proposal_id": pid, "status": "proposed"}

    def ontology_impact(self, proposal_id: str) -> dict:
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            prop = conn.execute("SELECT * FROM research_ontology_proposals WHERE id=?", (proposal_id,)).fetchone()
            if not prop:
                raise KeyError(proposal_id)
            if prop["status"] not in {"proposed", "impact_ready"}:
                raise ValueError("impact can only be computed before pilot publication")
            impacted = self._recompute_ontology_impact(conn, prop)
            conn.execute("UPDATE research_ontology_proposals SET status='impact_ready',updated_at=? WHERE id=?", (_now(),proposal_id))
            conn.commit()
            return {"proposal_id": proposal_id, "impacted": impacted, "count": len(impacted)}

    def _recompute_ontology_impact(self, conn: sqlite3.Connection,
                                   prop: sqlite3.Row) -> list[str]:
        """Rebuild the impact set from current active base-version revisions."""
        changed = set(json.loads(prop["changed_keys_json"]))
        conn.execute("DELETE FROM research_ontology_impacts WHERE proposal_id=?", (prop["id"],))
        impacted: list[str] = []
        rows = conn.execute(
            """SELECT i.id,i.ontology_keys_json FROM research_interpretations i
               JOIN research_batch_items bi ON bi.interpretation_id=i.id
               WHERE i.ontology_version=? AND i.validity_status='active'""",
            (prop["base_version"],),
        )
        for row in rows:
            keys = set(json.loads(row["ontology_keys_json"] or "[]"))
            overlap = sorted(changed & keys)
            if overlap:
                conn.execute(
                    """INSERT INTO research_ontology_impacts
                       (proposal_id,interpretation_id,impacted_keys_json,requires_rereview)
                       VALUES (?,?,?,1)""",
                    (prop["id"], row["id"], json.dumps(overlap)),
                )
                impacted.append(row["id"])
        return impacted

    def publish_ontology_pilot(self, proposal_id: str) -> dict:
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            prop = conn.execute("SELECT * FROM research_ontology_proposals WHERE id=?", (proposal_id,)).fetchone()
            if not prop:
                raise KeyError(proposal_id)
            if prop["status"] != "impact_ready":
                raise ValueError("impact analysis is required before pilot publish")
            base = conn.execute("SELECT payload_json FROM research_ontology_versions WHERE version=?", (prop["base_version"],)).fetchone()
            changed = set(json.loads(prop["changed_keys_json"]))
            known = _concept_ids(json.loads(base["payload_json"])) | _concept_ids(json.loads(prop["payload_json"]))
            if changed - known:
                raise ValueError("proposal changed concept ids are no longer verifiable")
            # Impact is a transactional publication precondition, not a stale
            # earlier snapshot: include records created/reviewed since preview.
            ids = self._recompute_ontology_impact(conn, prop)
            now = _now()
            conn.execute("INSERT INTO research_ontology_versions(version,parent_version,status,payload_json,created_at,published_at) VALUES (?,?,?,?,?,?)",
                         (prop["proposed_version"],prop["base_version"],"pilot",prop["payload_json"],now,now))
            if ids:
                marks = ",".join("?" for _ in ids)
                conn.execute(f"UPDATE research_interpretations SET validity_status='stale',updated_at=? WHERE id IN ({marks})", (now,*ids))
            conn.execute("UPDATE research_ontology_proposals SET status='pilot_published',updated_at=? WHERE id=?", (now,proposal_id))
            conn.commit()
            return {"proposal_id": proposal_id, "version": prop["proposed_version"], "stale_interpretations": ids}

    def partial_rereview(self, proposal_id: str, interpretation_ids: list[str],
                         relabels: dict[str, dict] | None = None) -> dict:
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            impacts = {r[0]: r[1] for r in conn.execute(
                "SELECT interpretation_id,impacted_keys_json FROM research_ontology_impacts WHERE proposal_id=?",
                (proposal_id,),
            )}
            allowed = set(impacts)
            invalid = sorted(set(interpretation_ids) - allowed)
            if invalid:
                raise ValueError(f"interpretations outside impact set: {invalid}")
            prop = conn.execute("SELECT proposed_version,payload_json,status FROM research_ontology_proposals WHERE id=?", (proposal_id,)).fetchone()
            if not prop:
                raise KeyError(proposal_id)
            if prop["status"] != "pilot_published":
                raise ValueError("pilot ontology must be published before local rereview")
            proposed_payload = json.loads(prop["payload_json"])
            new_ids = _concept_ids(proposed_payload)
            dimensions = proposed_payload.get("dimensions") or {}
            now = _now()
            created = []
            for iid in interpretation_ids:
                row = conn.execute("SELECT * FROM research_interpretations WHERE id=?", (iid,)).fetchone()
                if not row:
                    raise KeyError(iid)
                current = conn.execute(
                    "SELECT interpretation_id FROM research_batch_items WHERE batch_id=? AND source_id=?",
                    (row["batch_id"], row["source_id"]),
                ).fetchone()
                if (not current or current["interpretation_id"] != iid or
                        row["validity_status"] != "stale"):
                    raise ValueError(f"interpretation {iid} is not the current stale head")
                change = (relabels or {}).get(iid) or {}
                unexpected = set(change) - {"ontology_keys", "payload_patch"}
                if unexpected:
                    raise ValueError(f"unsupported relabel fields for {iid}: {sorted(unexpected)}")
                keys = sorted(set(change.get("ontology_keys", json.loads(row["ontology_keys_json"] or "[]"))))
                unknown = set(keys) - new_ids
                if unknown:
                    raise ValueError(f"interpretation {iid} requires revision for removed concepts: {sorted(unknown)}")
                payload = json.loads(row["payload_json"])
                payload.update(change.get("payload_patch") or {})
                for dimension in ("mapping_status", "update_object", "research_role"):
                    value = payload.get(dimension)
                    if value is not None and value not in set(dimensions.get(dimension) or []):
                        raise ValueError(f"{dimension} not defined by {prop['proposed_version']}: {value}")
                version = conn.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM research_interpretations WHERE batch_id=? AND source_record_id=?",
                    (row["batch_id"], row["source_record_id"]),
                ).fetchone()[0]
                new_iid = _id("RI")
                # the re-review copy keeps the original's release binding and
                # content state — a NULL-binding copy would be refused at
                # approval as a legacy-structure record, and state would reset
                conn.execute("""INSERT INTO research_interpretations
                    (id,batch_id,source_record_id,source_id,source_file_id,parse_run_id,snapshot_id,
                     snapshot_sha256,ontology_version,ontology_keys_json,schema_version,version,payload_json,
                     validation_status,agent_review_status,human_adoption_status,validity_status,
                     release_id,definition_refs_json,content_state,source_metadata_record_id,
                     supersedes_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'passed','pending','pending','active',?,?,?,?,?,?,?)""",
                    (new_iid,row["batch_id"],row["source_record_id"],row["source_id"],row["source_file_id"],
                     row["parse_run_id"],row["snapshot_id"],row["snapshot_sha256"],prop["proposed_version"],
                     json.dumps(keys,ensure_ascii=False),row["schema_version"],version,
                     json.dumps(payload,ensure_ascii=False),
                     _row_value(row,"release_id"),_row_value(row,"definition_refs_json"),_row_value(row,"content_state"),
                     _row_value(row,"source_metadata_record_id"),
                     iid,now,now))
                snapshot = _row(conn.execute(
                    "SELECT * FROM research_text_snapshots WHERE id=?", (row["snapshot_id"],)
                ).fetchone())
                self._insert_claims(
                    conn, layer="interpretation", record_id=new_iid, snapshot=snapshot,
                    claims=self._record_claims(conn, "interpretation", iid),
                )
                conn.execute(
                    "UPDATE research_batch_items SET interpretation_id=?,updated_at=? WHERE batch_id=? AND source_id=?",
                    (new_iid,now,row["batch_id"],row["source_id"]),
                )
                conn.execute(
                    "INSERT INTO research_ontology_impacts(proposal_id,interpretation_id,impacted_keys_json,requires_rereview) VALUES (?,?,?,1)",
                    (proposal_id,new_iid,impacts[iid]),
                )
                created.append({"supersedes_id": iid, "interpretation_id": new_iid, "version": version,
                                "ontology_keys": keys})
            conn.commit()
            return {"proposal_id": proposal_id, "rereview_revisions": created}
