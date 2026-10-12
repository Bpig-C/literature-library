"""Next-version research services (contract v5).

Covers the layers and loops the pilot service did not have yet: metadata
records, research units, the feedback→formal-revision closed loop, citation
edges, task packages with idempotent receipts, and cross-paper exports.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from .storage.runtime import material_ready

from .research_catalog import (catalog_available, catalog_conn, catalog_work_identity,
                               propagate_metadata, work_exists)
from .research_context import ResearchContext
from .research_definitions import (
    DefinitionService,
    validate_payload_against_definition,
)
from .research_errors import (
    dependency_unavailable,
    invalid_payload,
    not_found_error,
    revision_conflict,
)
from .research_operations import (RECEIPT_RECOVERABLE_KINDS, canonical_request_digest,
                                  committed_effects, record_operation_effect,
                                  set_current_operation)
from .research_schema import CONTRACT, compute_environment_id, verify_schema
from .research_stability import (assess_metadata_dependency, clean_identifier,
                                 current_metadata_head)
from .research_service import (_c, _require_environment, _require_reviewer_identity,
                               _row_value, research_v5_available)


CONTENT_STATES = tuple(CONTRACT["statuses"]["content_state"])
FEEDBACK_OUTCOMES = tuple(CONTRACT["statuses"]["feedback_outcome"])
MATCH_STATUSES = tuple(CONTRACT["statuses"]["reference_match"])

# Serializes receipt claiming in-process; cross-process claim races are
# handled by the INSERT + BEGIN IMMEDIATE below.
_receipt_lock = threading.Lock()
_REQUEST_ENV_UNSET = object()

_FEEDBACK_TARGET_TABLES = {
    "metadata": "research_metadata_records",
    "source_record": "research_source_records",
    "interpretation": "research_interpretations",
    "unit": "research_units",
    "ontology": "research_ontology_proposals",
}
_REVISION_TABLES = {
    "RMR": ("research_metadata_records", "metadata"),
    "RSR": ("research_source_records", "source_record"),
    "RI": ("research_interpretations", "interpretation"),
    "RU": ("research_units", "unit"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def _export_output_id(kind: str, input_manifest: dict) -> str:
    """Deterministic export identity over its fixed inputs (contract v5 B7).

    The same inputs always produce the same output_id, so a later invalidation
    of any pinned record version can be detected by re-deriving the id.
    """
    canonical = json.dumps({"kind": kind, "inputs": input_manifest},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "OUT-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _register_output(self_conn: sqlite3.Connection, kind: str, batch_id: str | None,
                     output_id: str, input_manifest: dict,
                     output_payload: dict | None = None) -> list[str]:
    """Lightweight output registry (B7): persist the exact input manifest behind
    each emitted output_id so a historical output can always answer "which
    inputs produced this" and later exports can name their predecessors."""
    previous = [r[0] for r in self_conn.execute(
        "SELECT output_id FROM research_output_registry WHERE kind=? AND COALESCE(batch_id,'')=? "
        "AND output_id<>? ORDER BY created_at",
        (kind, batch_id or "", output_id))]
    self_conn.execute(
        """INSERT INTO research_output_registry
           (output_id,kind,batch_id,inputs_json,output_json,created_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(output_id,kind) DO UPDATE SET
             output_json=COALESCE(research_output_registry.output_json,excluded.output_json)""",
        (output_id, kind, batch_id,
         json.dumps(input_manifest, ensure_ascii=False),
         json.dumps(output_payload, ensure_ascii=False) if output_payload is not None else None,
         _now()))
    return previous


LOCATOR_KINDS = ("text_offset", "page", "figure_region", "html_anchor", "markdown_line")


def _validated_locator(locator: Any, snapshot: dict | None = None) -> dict:
    """U19 证据回查链（引用/保留证据入口）：委托共享校验并绑定快照核对。

    形状与可核对性规则见 :func:`research_definitions.validate_locator`；
    C/D 提交入口走同一条规则，不允许两套口径。
    """
    from .research_definitions import validate_locator as _shared_validate
    from .research_errors import invalid_payload as _invalid
    try:
        return _shared_validate(locator, snapshot)
    except ValueError as error:
        raise _invalid(str(error)) from error


def _canonical_current_head(conn: sqlite3.Connection, table: str, key_columns: dict[str, object]) -> dict | None:
    where = " AND ".join(f"{column}=?" for column in key_columns)
    return _row(conn.execute(
        f"SELECT * FROM {table} WHERE {where} ORDER BY version DESC LIMIT 1",
        tuple(key_columns.values()),
    ).fetchone())


def _revision_work_id(conn: sqlite3.Connection, table: str, revision: sqlite3.Row) -> str | None:
    """Work a revision belongs to; source/interpretation rows reach it via source_id."""
    if "work_id" in revision.keys():
        return revision["work_id"]
    source_id = revision["source_id"] if "source_id" in revision.keys() else None
    if not source_id:
        return None
    row = conn.execute("SELECT work_id FROM research_sources WHERE id=?", (source_id,)).fetchone()
    return row["work_id"] if row else None


class ResearchNextService:
    """Layer-generic records, feedback closure, citations, packages, exports."""

    def __init__(self, context: ResearchContext):
        self.context = context

    # ----- infrastructure -----
    def _write_conn(self) -> sqlite3.Connection:
        self.context.require_writable()
        if not verify_schema(self.context)["ok"]:
            raise RuntimeError("research schema is not initialized; run migration apply explicitly")
        return self.context.connect()

    def _release_binding(self, release_id: str | None, layer: str) -> tuple[str | None, str | None]:
        """Contract v5: every write binds a release bundle — the given one or
        the latest released bundle.  There is no unbound path left."""
        refs = DefinitionService(self.context).resolve_release(release_id)
        available = {ref["layer"] for ref in refs["definition_refs"]}
        if layer not in available:
            raise invalid_payload(f"release {refs['id']} has no definition for layer {layer}")
        return refs["id"], json.dumps(refs["definition_refs"], ensure_ascii=False)

    def _validate_against_release(self, release_id: str | None, layer: str,
                                  definition_refs_json: str | None, payload: dict) -> None:
        if not definition_refs_json:
            return
        refs = json.loads(definition_refs_json)
        # units validate against the source-record definition, wrapped as a
        # one-entry units list (that is how they are submitted)
        definition_layer = "source_record" if layer == "unit" else layer
        ref = next((r for r in refs if r["layer"] == definition_layer), None)
        if ref is None:
            raise invalid_payload(f"release {release_id} has no definition for layer {layer}")
        definition = DefinitionService(self.context).get_definition(definition_layer, ref["version"])
        check_payload = {"units": [payload]} if layer == "unit" else payload
        validate_payload_against_definition(definition_layer, check_payload, definition["payload"])

    def run_with_receipt(self, operation_id: str | None, task_kind: str,
                         fn: Callable[[], dict], *, target_id: str | None = None,
                         batch_id: str | None = None,
                         worker_owner: str | None = None,
                         request_digest: str | None = None,
                         request_environment_id: str | None | object = _REQUEST_ENV_UNSET) -> dict:
        """Execute a mutation once per operation_id; replays the stored receipt.

        Controller A5: the receipt is *claimed* (INSERT under BEGIN IMMEDIATE,
        serialized in-process by a lock) before the mutation runs, so two
        concurrent invocations of the same operation can no longer both run
        ``fn`` and double-write.  Reusing an operation_id for a different
        task_kind/target_id, or for a different request payload (B4), is a
        revision_conflict, not a silent replay.

        B4 recovery: business methods journal their public result into
        ``research_operation_effects`` inside the same transaction as the
        business write.  When the process dies between that commit and the
        receipt finalize, the retry finds the committed effects and finalizes
        the receipt from them instead of re-executing ``fn`` — the business
        object is never written twice.  A stale in-flight claim with *no*
        journal rows means nothing was committed, so the claim is safe to
        reclaim and run.
        """
        if not operation_id or not str(operation_id).strip():
            return fn()
        # B4: explicitly refuse runners outside the effect-journal protocol —
        # a committed write that never journaled its effect cannot be
        # distinguished from a rollback, so recovery would be a promise the
        # wrapper cannot keep.
        if task_kind not in RECEIPT_RECOVERABLE_KINDS:
            raise invalid_payload(
                f"task kind '{task_kind}' is not a receipt-recoverable operation: "
                "recovery requires a first-party business method that journals its "
                "effect in-transaction (supported: "
                f"{sorted(RECEIPT_RECOVERABLE_KINDS)})")
        operation_id = str(operation_id).strip()
        # B1/B4(R6): the receipt is bound to the environment that earned it.
        # First run, replay and recovery check the SAME binding — a replay
        # carrying another store's identity can never return a success that
        # was recorded elsewhere.
        receipt_env = compute_environment_id(self.context.library_root, self.context.db_path)
        # The request's declared environment is part of the replay gate.  The
        # wrapped mutation normally checks it too, but a completed replay never
        # calls ``fn``; without this explicit preflight HTTP could return an old
        # success for a request that names another environment.
        if request_environment_id is not _REQUEST_ENV_UNSET and (
                not request_environment_id or str(request_environment_id).strip() != receipt_env):
            raise revision_conflict(
                f"request environment_id {request_environment_id or '<missing>'} does not "
                f"match this research store ({receipt_env}); a receipt cannot be replayed "
                "for a differently bound request")
        with _receipt_lock:
            with closing(self._write_conn()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT task_kind,target_id,result_json,request_digest,environment_id "
                    "FROM research_task_receipts WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                if existing:
                    if (existing["task_kind"] or "") != task_kind or \
                            (existing["target_id"] or None) != (target_id or None):
                        raise revision_conflict(
                            f"operation_id {operation_id} was already used for "
                            f"{existing['task_kind']}/{existing['target_id'] or '-'}; "
                            "reusing it for a different meaning is a conflict")
                    if request_digest and existing["request_digest"] and \
                            existing["request_digest"] != request_digest:
                        raise revision_conflict(
                            f"operation_id {operation_id} was already used with a different "
                            "request payload (same key, different content is a conflict; "
                            "use a new operation_id)")
                    stored_env = existing["environment_id"]
                    if stored_env and stored_env != receipt_env:
                        raise revision_conflict(
                            f"operation_id {operation_id} succeeded in environment "
                            f"{stored_env}; this request targets {receipt_env}. A receipt "
                            "cannot be replayed across environments — issue a new "
                            "operation_id for the other store")
                    if existing["result_json"] in (None, "null"):
                        # In-flight claim without a finalized receipt: recover from
                        # the effect journal (business commit survived) or reclaim
                        # (nothing committed).
                        effects = committed_effects(conn, operation_id)
                        if effects:
                            result = effects[-1]
                            conn.execute(
                                "UPDATE research_task_receipts SET result_json=?,request_digest=? "
                                "WHERE operation_id=?",
                                (json.dumps(result, ensure_ascii=False),
                                 request_digest or existing["request_digest"], operation_id))
                            conn.commit()
                            result["receipt"] = {"operation_id": operation_id,
                                                 "replayed": True, "recovered": True}
                            return result
                        conn.execute(
                            "DELETE FROM research_task_receipts WHERE operation_id=?",
                            (operation_id,))
                    else:
                        result = json.loads(existing["result_json"])
                        result["receipt"] = {"operation_id": operation_id, "replayed": True}
                        conn.commit()
                        return result
                # claim before running: result_json='null' marks an in-flight operation
                conn.execute(
                    """INSERT INTO research_task_receipts
                       (operation_id,task_kind,target_id,batch_id,worker_owner,result_json,
                        request_digest,environment_id,created_at)
                       VALUES (?,?,?,?,?,'null',?,?,?)""",
                    (operation_id, task_kind, target_id, batch_id, worker_owner,
                     request_digest, receipt_env, _now()),
                )
                conn.commit()
            set_current_operation(operation_id)
            try:
                result = fn()
            except BaseException:
                # B4: the claim may outlive a business commit (an injected or
                # environmental failure after the business transaction committed).
                # When effects were journalized the in-flight claim is KEPT so
                # the retry recovers the committed result instead of re-running
                # the business method; only a rollback with no journal rows
                # drops the claim so a retry may run cleanly.
                with closing(self._write_conn()) as conn:
                    effects = committed_effects(conn, operation_id)
                    if not effects:
                        conn.execute(
                            "DELETE FROM research_task_receipts WHERE operation_id=? AND result_json='null'",
                            (operation_id,),
                        )
                        conn.commit()
                raise
            finally:
                set_current_operation(None)
            with closing(self._write_conn()) as conn:
                conn.execute(
                    "UPDATE research_task_receipts SET result_json=?,request_digest=? "
                    "WHERE operation_id=?",
                    (json.dumps(result, ensure_ascii=False), request_digest, operation_id),
                )
                conn.commit()
        result["receipt"] = {"operation_id": operation_id, "replayed": False}
        return result

    # ----- metadata records -----
    def submit_metadata_record(self, *, work_id: str, payload: dict,
                               supersedes_id: str | None = None,
                               release_id: str | None = None,
                               batch_id: str | None = None,
                               feedback_id: str | None = None,
                               expected_head_id: str | None = None,
                               submitted_by: str | None = None,
                               environment_id: str | None = None,
                               manual_reason: str | None = None) -> dict:
        if not work_id:
            raise invalid_payload("work_id is required")
        _require_environment(self.context, environment_id)
        if not work_exists(self.context, work_id):
            raise not_found_error(
                f"unknown work_id {work_id}: not in the catalog nor in research sources")
        release_bound, refs_json = self._release_binding(release_id, "metadata")
        self._validate_against_release(release_id, "metadata", refs_json, payload)
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = _canonical_current_head(conn, "research_metadata_records", {"work_id": work_id})
            if expected_head_id is not None and (latest["id"] if latest else None) != expected_head_id:
                raise revision_conflict("expected_head_id does not match the current metadata head")
            # B2: only genuinely NEW revisions need a generation origin; an
            # identical replay of the current head creates nothing and stays
            # idempotent without one.
            if not (submitted_by or "").strip() and (supersedes_id or not latest):
                raise invalid_payload(
                    "new metadata records require submitted_by (generation origin); "
                    "omitting it must not masquerade as historical unknown")
            if latest and not supersedes_id:
                if json.loads(latest["payload_json"]) == payload:
                    result = self._public_record("metadata", latest, created=False)
                    record_operation_effect(conn, result)
                    conn.commit()
                    return result
                raise revision_conflict("non-identical metadata submission requires supersedes_id")
            if supersedes_id:
                old = conn.execute(
                    "SELECT * FROM research_metadata_records WHERE id=? AND work_id=?",
                    (supersedes_id, work_id),
                ).fetchone()
                if not old:
                    raise not_found_error(supersedes_id)
                if not latest or supersedes_id != latest["id"] or latest["validity_status"] != "active":
                    raise revision_conflict("supersedes_id must be the current active metadata head")
            elif latest:
                raise revision_conflict("existing metadata record requires supersedes_id")
            version = (latest["version"] + 1) if latest else 1
            record_id, now = _id("RMR"), _now()
            conn.execute(
                """INSERT INTO research_metadata_records
                (id,batch_id,work_id,version,supersedes_id,payload_json,content_state,
                 validation_status,agent_review_status,human_adoption_status,validity_status,
                 release_id,definition_refs_json,feedback_id,submitted_by,created_at,updated_at)
                VALUES (?,?,?,?,?,?,'needs_review','passed','pending','pending','active',?,?,?,?,?,?)""",
                (record_id, batch_id, work_id, version, supersedes_id,
                 json.dumps(payload, ensure_ascii=False),
                 release_bound, refs_json, feedback_id,
                 (submitted_by or "").strip() or None, now, now),
            )
            if supersedes_id:
                conn.execute(
                    "UPDATE research_metadata_records SET validity_status='superseded',updated_at=? WHERE id=?",
                    (now, supersedes_id),
                )
            self._link_feedback(conn, feedback_id, record_id, now)
            row = conn.execute("SELECT * FROM research_metadata_records WHERE id=?", (record_id,)).fetchone()
            result = self._public_record("metadata", row, created=True)
            record_operation_effect(conn, result)
            conn.commit()
            return result

    # ----- research units -----
    def submit_unit(self, *, batch_id: str, source_record_id: str, unit_key: str,
                    payload: dict, shared_items: list | None = None,
                    gaps: list | None = None, extensions: list | None = None,
                    supersedes_id: str | None = None,
                    release_id: str | None = None,
                    expected_head_id: str | None = None,
                    submitted_by: str | None = None,
                    environment_id: str | None = None) -> dict:
        if not unit_key:
            raise invalid_payload("unit_key is required")
        _require_environment(self.context, environment_id)
        if not isinstance(payload, dict):
            raise invalid_payload("unit payload must be an object")
        payload = dict(payload)
        payload["unit_key"] = unit_key
        # units always bind a release: the given one, else the current release bundle
        release_bound, refs_json = self._release_binding(
            release_id or DefinitionService(self.context).resolve_release(None)["id"], "source_record")
        refs = DefinitionService(self.context).resolve_release(release_bound)
        ref = next(r for r in refs["definition_refs"] if r["layer"] == "source_record")
        definition = DefinitionService(self.context).get_definition("source_record", ref["version"])
        validate_payload_against_definition("source_record", {"units": [payload]}, definition["payload"])
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            record = conn.execute(
                "SELECT * FROM research_source_records WHERE id=? AND batch_id=?",
                (source_record_id, batch_id),
            ).fetchone()
            if not record:
                raise not_found_error(f"{batch_id}/{source_record_id}")
            if record["validity_status"] != "active":
                raise revision_conflict("units bind the active source-record head")
            source = conn.execute("SELECT work_id FROM research_sources WHERE id=?",
                                  (record["source_id"],)).fetchone()
            latest = _canonical_current_head(conn, "research_units", {
                "source_record_id": source_record_id, "unit_key": unit_key})
            if expected_head_id is not None and (latest["id"] if latest else None) != expected_head_id:
                raise revision_conflict("expected_head_id does not match the current unit head")
            # B2: only genuinely NEW units need a generation origin; identical
            # replay stays idempotent without one.
            if not (submitted_by or "").strip() and (supersedes_id or not latest):
                raise invalid_payload(
                    "new units require submitted_by (generation origin); "
                    "omitting it must not masquerade as historical unknown")
            if latest and not supersedes_id:
                # B7(R5): extensions are part of the unit's identity — a
                # "same payload, different extensions" retry is NOT an
                # idempotent replay and must not silently return old content.
                if (json.loads(latest["payload_json"]) == payload and
                        json.loads(latest["shared_items_json"] or "[]") == (shared_items or []) and
                        json.loads(latest["gaps_json"] or "[]") == (gaps or []) and
                        json.loads(latest["extensions_json"] or "[]") == (extensions or [])):
                    result = self._public_record("unit", latest, created=False)
                    record_operation_effect(conn, result)
                    conn.commit()
                    return result
                raise revision_conflict(
                    "non-identical unit submission (payload/shared_items/gaps/extensions "
                    "differ) requires supersedes_id")
            if supersedes_id:
                old = conn.execute(
                    "SELECT * FROM research_units WHERE id=? AND source_record_id=? AND unit_key=?",
                    (supersedes_id, source_record_id, unit_key),
                ).fetchone()
                if not old:
                    raise not_found_error(supersedes_id)
                if not latest or supersedes_id != latest["id"] or latest["validity_status"] != "active":
                    raise revision_conflict("supersedes_id must be the current active unit head")
            elif latest:
                raise revision_conflict("existing unit requires supersedes_id")
            version = (latest["version"] + 1) if latest else 1
            unit_id, now = _id("RU"), _now()
            conn.execute(
                """INSERT INTO research_units
                (id,batch_id,work_id,source_record_id,unit_key,version,supersedes_id,payload_json,
                 shared_items_json,gaps_json,extensions_json,content_state,validation_status,
                 agent_review_status,human_adoption_status,validity_status,
                 release_id,definition_refs_json,submitted_by,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?, 'needs_review','passed','pending','pending','active',?,?,?,?,?)""",
                (unit_id, batch_id, source["work_id"], source_record_id, unit_key, version,
                 supersedes_id, json.dumps(payload, ensure_ascii=False),
                 json.dumps(shared_items or [], ensure_ascii=False),
                 json.dumps(gaps or [], ensure_ascii=False),
                 json.dumps(extensions or [], ensure_ascii=False),
                 release_bound, refs_json, (submitted_by or "").strip() or None, now, now),
            )
            if supersedes_id:
                conn.execute(
                    "UPDATE research_units SET validity_status='superseded',updated_at=? WHERE id=?",
                    (now, supersedes_id),
                )
            row = conn.execute("SELECT * FROM research_units WHERE id=?", (unit_id,)).fetchone()
            result = self._public_record("unit", row, created=True)
            record_operation_effect(conn, result)
            conn.commit()
            return result

    def units_for_record(self, source_record_id: str, *, content_state: str | None = None) -> dict:
        with closing(self.context.connect(read_only=True)) as conn:
            where, params = ["source_record_id=?"], [source_record_id]
            if content_state:
                where.append("content_state=?")
                params.append(content_state)
            rows = conn.execute(
                f"SELECT * FROM research_units WHERE {' AND '.join(where)} ORDER BY unit_key,version",
                params,
            ).fetchall()
            return {"source_record_id": source_record_id,
                    "items": [self._public_record("unit", row) for row in rows]}

    # ----- generic review / adoption for metadata and units -----
    def review_record(self, layer: str, record_id: str, *, decision: str, note: str = "",
                      actor_id: str | None = None) -> dict:
        if layer not in {"metadata", "unit"}:
            raise invalid_payload("use the layer-specific review endpoints for source records and interpretations")
        if decision not in CONTRACT["statuses"]["agent_review"]:
            raise invalid_payload("invalid agent review decision")
        table = "research_metadata_records" if layer == "metadata" else "research_units"
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise not_found_error(record_id)
            if decision == "approved":
                from .research_service import _require_reviewer_identity
                _require_reviewer_identity(decision, actor_id, row["submitted_by"],
                                           action=f"{layer} agent review")
                if row["validation_status"] != "passed" or row["validity_status"] != "active":
                    raise invalid_payload("approval requires passed validation and active validity")
                if not row["release_id"] or not row["definition_refs_json"]:
                    raise invalid_payload(
                        "legacy-structure record cannot be approved as stable; "
                        "re-submit it under the released definition first")
                self._validate_against_release(row["release_id"], layer,
                                               row["definition_refs_json"],
                                               json.loads(row["payload_json"]))
            content_state = "stable" if decision == "approved" else "needs_completion"
            now = _now()
            already_approved = row["agent_review_status"] == "approved" and \
                row["content_state"] == "stable"
            conn.execute(
                f"UPDATE {table} SET agent_review_status=?,content_state=?,updated_at=? WHERE id=?",
                (decision, content_state, now, record_id),
            )
            if decision == "approved":
                # baseline switch happens at approval: retire still-active predecessors
                if layer == "metadata":
                    conn.execute(
                        """UPDATE research_metadata_records SET validity_status='superseded',updated_at=?
                           WHERE work_id=? AND version<? AND validity_status='active' AND id!=?""",
                        (now, row["work_id"], row["version"], record_id),
                    )
                else:
                    conn.execute(
                        """UPDATE research_units SET validity_status='superseded',updated_at=?
                           WHERE source_record_id=? AND unit_key=? AND version<?
                             AND validity_status='active' AND id!=?""",
                        (now, row["source_record_id"], row["unit_key"], row["version"], record_id),
                    )
            if not already_approved or decision != "approved":
                conn.execute(
                    """INSERT INTO research_review_events
                       (id,record_layer,record_id,actor_type,actor_id,decision,note,created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (_id("RR"), layer, record_id, "agent", actor_id, decision, note, now),
                )
            conn.commit()
        propagation = None
        if layer == "metadata" and decision == "approved":
            # A6/B9: metadata approval must reach works + metadata_extractions,
            # but research verification and catalog propagation are separately
            # truthful — a propagation failure must neither erase the committed
            # review nor masquerade as success; it is reported and retryable.
            try:
                propagation = self.propagate_metadata_record(record_id)["catalog_propagation"]
            except Exception as error:  # noqa: BLE001 — surfaced, never swallowed
                propagation = {"status": "failed", "error": str(error),
                               "record_id": record_id,
                               "retry": {"method": "POST",
                                         "path": f"/api/research/records/metadata/{record_id}/propagate"}}
        return {"record_id": record_id, "layer": layer,
                "agent_review_status": decision, "content_state": content_state,
                "actor_type": "agent", "actor_id": actor_id,
                "catalog_propagation": propagation}

    def get_output_history(self, output_id: str) -> dict:
        """B7(R6): fetch a historical output by identity — its kind, the exact
        input manifest that produced it, and the row states at emission time
        (re-derived rows carry CURRENT state; the manifest is the frozen
        record of what the output actually consumed)."""
        with closing(self.context.connect(read_only=True)) as conn:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_output_registry'"
            ).fetchone():
                raise not_found_error(output_id)
            rows = conn.execute(
                """SELECT output_id,kind,batch_id,inputs_json,output_json,created_at
                   FROM research_output_registry WHERE output_id=? ORDER BY created_at""",
                (output_id,)).fetchall()
        if not rows:
            raise not_found_error(
                f"no registered output with id {output_id}; historical retrieval needs a "
                "registered output")
        entries = []
        for r in rows:
            snapshot = json.loads(r["output_json"]) if r["output_json"] else None
            entries.append({"output_id": r["output_id"], "kind": r["kind"],
                            "batch_id": r["batch_id"], "created_at": r["created_at"],
                            "input_manifest": json.loads(r["inputs_json"]),
                            "output_snapshot": snapshot,
                            "historical_content_available": snapshot is not None})
        return {"output_id": output_id, "versions": entries,
                "note": "output_snapshot 是生成当时冻结的实际 C/D/U、claims、evidence 与状态；"
                        "旧版仅有 manifest 的行会明确标为 historical_content_available=false"}

    def metadata_impact(self, record_id: str) -> dict:
        """U24: the local dependency impact of one metadata record — which
        interpretations pinned it, and what their current review/consumption
        state is.  A metadata revision that loses approval or is superseded
        marks its dependents ``review_pending`` instead of silently keeping
        them usable as if nothing changed."""
        with closing(self.context.connect(read_only=True)) as conn:
            row = conn.execute(
                "SELECT id, work_id, version, content_state, agent_review_status, "
                "validity_status FROM research_metadata_records WHERE id=?",
                (record_id,)).fetchone()
            if not row:
                raise not_found_error(record_id)
            dependents = []
            for dep in conn.execute(
                """SELECT id, version, batch_id, agent_review_status,
                   validity_status, source_metadata_record_id
                   FROM research_interpretations
                   WHERE source_metadata_record_id=?
                   ORDER BY batch_id, id""", (record_id,)):
                dependents.append({**dict(dep), "metadata_review_pending":
                                   row["agent_review_status"] != "approved"
                                   or row["content_state"] != "stable"})
        return {"metadata_record": dict(row),
                "dependent_interpretations": dependents,
                "note": "局部依赖清单：仅列出显式钉定该元数据记录的解释；未钉定的历史解释如实不出现在依赖中"}

    def _persist_propagation_state(self, record_id: str, state: dict) -> None:
        """B9: propagation state lives on the record — visible and retryable
        after refresh/restart, not only inside one response."""
        with closing(self._write_conn()) as conn:
            conn.execute(
                "UPDATE research_metadata_records SET propagation_state_json=?,updated_at=? WHERE id=?",
                (json.dumps(state, ensure_ascii=False), _now(), record_id))
            conn.commit()

    def propagate_metadata_record(self, record_id: str) -> dict:
        """Re-run catalog propagation for an approved metadata record (B9).

        Only the CURRENT active head may propagate: a superseded revision is a
        late/stale task and is refused, because replaying it would roll the
        catalog projection back to older year/type/status.  User-facing
        rollback goes through a NEW revision, never through this retry.
        Idempotent for the current head: re-propagation supersedes the
        previous research-v5 extraction rows and rewrites the projection.
        """
        with closing(self.context.connect(read_only=True)) as conn:
            row = conn.execute(
                """SELECT * FROM research_metadata_records WHERE id=?""", (record_id,)).fetchone()
            current = conn.execute(
                """SELECT id FROM research_metadata_records
                   WHERE work_id=? AND validity_status='active'
                   ORDER BY version DESC LIMIT 1""", (row["work_id"] if row else "",)).fetchone()
        if not row:
            raise not_found_error(record_id)
        if row["agent_review_status"] != "approved" or row["content_state"] != "stable":
            raise invalid_payload(
                "catalog propagation requires an approved, stable metadata record; "
                "a pending revision has nothing to propagate")
        if not current or current["id"] != record_id or row["validity_status"] != "active":
            raise revision_conflict(
                f"metadata record {record_id} is superseded; catalog propagation only "
                "applies the current active revision (a rollback is a new revision, "
                "not a late retry)")
        # Persist intent BEFORE crossing into the catalog database.  If the
        # state write itself fails, no catalog mutation has occurred.  If the
        # final confirmation fails after a successful catalog commit, this
        # durable pending marker remains diagnostic and a retry is idempotent.
        pending = {"status": "pending", "attempted_at": _now(),
                   "record_id": record_id,
                   "retry": {"method": "POST",
                             "path": f"/api/research/records/metadata/{record_id}/propagate"}}
        self._persist_propagation_state(record_id, pending)
        try:
            propagation = propagate_metadata(
                self.context, row["work_id"], json.loads(row["payload_json"]),
                record_id=record_id)
        except Exception as error:  # noqa: BLE001 — persist + surface
            state = {"status": "failed", "error": str(error),
                     "attempted_at": _now(), "record_id": record_id}
            self._persist_propagation_state(record_id, state)
            raise
        state = {**(propagation or {}), "status": "propagated",
                 "attempted_at": _now(), "record_id": record_id}
        self._persist_propagation_state(record_id, state)
        return {"record_id": record_id, "work_id": row["work_id"],
                "catalog_propagation": state}

    def adopt_record(self, layer: str, record_id: str, *, decision: str, note: str = "",
                     scope: dict | None = None, actor_id: str | None = None) -> dict:
        """Human adoption overlay for metadata/unit records (never gates consumption).

        ``scope`` records partial adoption (A7): which axes/claims the human
        decision covers, stored on the review event for traceability.
        """
        if layer not in {"metadata", "unit"}:
            raise invalid_payload("use the layer-specific adoption endpoints for source records and interpretations")
        if decision not in CONTRACT["statuses"]["human_adoption"] or decision == "pending":
            raise invalid_payload("human decision must be adopted or rejected")
        _require_reviewer_identity(decision, actor_id, action=f"{layer} human adoption")
        table = "research_metadata_records" if layer == "metadata" else "research_units"
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise not_found_error(record_id)
            if decision == "adopted" and (row["agent_review_status"] != "approved" or
                                          row["validity_status"] != "active"):
                raise invalid_payload("adoption requires an approved, active record")
            if decision == "adopted" and row["content_state"] != "stable":
                raise invalid_payload("adoption requires stable content")
            now = _now()
            # B6: adoption scope is a first-class fact on the record too
            conn.execute(f"""UPDATE {table} SET human_adoption_status=?,
                human_adoption_scope_json=?,updated_at=? WHERE id=?""",
                (decision,
                 json.dumps(scope, ensure_ascii=False) if scope is not None else None,
                 now, record_id))
            conn.execute(
                """INSERT INTO research_review_events
                   (id,record_layer,record_id,actor_type,actor_id,decision,scope_json,note,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (_id("RR"), layer, record_id, "human", actor_id, decision,
                 json.dumps(scope, ensure_ascii=False) if scope is not None else None,
                 note, now),
            )
            conn.commit()
            return {"record_id": record_id, "layer": layer,
                    "human_adoption_status": decision,
                    "content_state": row["content_state"], "scope": scope,
                    "actor_type": "human", "actor_id": actor_id}

    def _public_record(self, layer: str, row: sqlite3.Row, *, created: bool | None = None) -> dict:
        item = dict(row)
        payload = item.pop("payload_json")
        item["payload"] = json.loads(payload)
        for column in ("shared_items_json", "gaps_json", "extensions_json", "definition_refs_json"):
            if column in item:
                item[column[: -len("_json")]] = json.loads(item.pop(column) or "[]")
        # B9: the persisted catalog-propagation state travels with the record
        # so a failure stays visible after refresh/restart.
        if "propagation_state_json" in item:
            item["propagation_state"] = json.loads(item.pop("propagation_state_json") or "null")
        if created is not None:
            item["created"] = created
        item["layer"] = layer
        return item

    # ----- feedback → formal revision closed loop -----
    def open_feedback(self, *, layer: str, target_id: str, explicit_claim: str,
                      detail: str = "", work_id: str | None = None,
                      batch_id: str | None = None, target_version: int | None = None) -> dict:
        # 工单 LL-UX-EVIDENCE-20260914（工作包 B）：page_display 是面向页面
        # 显示缺陷的最小扩展层——目标即 work 本身，不落在研究记录表上；
        # 闭环走“实际修复+复验说明”，不要求虚构论文内容修订。
        if layer not in _FEEDBACK_TARGET_TABLES and layer != "page_display":
            raise invalid_payload(f"unknown feedback layer: {layer}")
        if not explicit_claim.strip():
            raise invalid_payload("explicit_claim is required")
        if layer != "page_display" and not (target_id or "").strip():
            raise invalid_payload("target_id is required for this layer")
        table = _FEEDBACK_TARGET_TABLES.get(layer)
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if layer == "page_display":
                if not (work_id or target_id):
                    raise invalid_payload("page_display 反馈必须提供 work_id（页面所属文献）")
                resolved_work_id = work_id or target_id
                if not work_exists(self.context, resolved_work_id):
                    raise not_found_error(f"unknown work_id {resolved_work_id}")
                resolved_target_id = target_id or resolved_work_id
                resolved_target_version = None
                resolved_batch_id = batch_id
                target = None
            else:
                target = conn.execute(f"SELECT * FROM {table} WHERE id=?", (target_id,)).fetchone()
                if not target:
                    raise not_found_error(f"feedback target not found in {table}: {target_id}")
                if target_version is not None and layer != "ontology" and \
                        int(target["version"]) != int(target_version):
                    raise invalid_payload(
                        f"target_version {target_version} does not match the current "
                        f"head version {target['version']} of {target_id}")
                target_work = None if layer == "ontology" else \
                    _revision_work_id(conn, table, target)
                resolved_work_id = work_id or target_work
                if resolved_work_id and not work_exists(self.context, resolved_work_id):
                    raise not_found_error(f"unknown work_id {resolved_work_id}")
                resolved_target_id = target_id
                resolved_target_version = (
                    target_version if target_version is not None else
                    (target["version"] if layer != "ontology" else None))
                resolved_batch_id = batch_id or (target["batch_id"] if layer != "ontology" else None)
            feedback_id, now = _id("RF"), _now()
            conn.execute(
                """INSERT INTO research_feedback
                (id,layer,target_id,target_version,work_id,batch_id,explicit_claim,detail,
                 status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,'open',?,?)""",
                (feedback_id, layer, resolved_target_id,
                 resolved_target_version,
                 resolved_work_id, resolved_batch_id,
                 explicit_claim.strip(), detail.strip(), now, now),
            )
            conn.commit()
        return {"feedback_id": feedback_id, "status": "open"}

    def link_feedback_revision(self, feedback_id: str, formal_revision_id: str) -> dict:
        """Bind an explicit feedback to the formal revision that addresses it (A4/B2).

        The revision must exist, be recognizable, and belong to the same work
        lineage as the feedback target; binding a fabricated or foreign
        revision id is rejected here so it can never be used later to claim
        "corrected".  Binding only records the *submitted* state — the outcome
        "corrected" additionally requires verified correction (close_feedback).
        """
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM research_feedback WHERE id=?", (feedback_id,)).fetchone()
            if not row:
                raise not_found_error(feedback_id)
            if row["status"] == "closed":
                raise revision_conflict("feedback already closed")
            prefix = next((p for p in _REVISION_TABLES if formal_revision_id.startswith(p + "-")), None)
            if not prefix:
                raise invalid_payload(
                    f"formal_revision_id {formal_revision_id} is not a recognized revision id")
            table, rev_layer = _REVISION_TABLES[prefix]
            revision = conn.execute(
                f"SELECT * FROM {table} WHERE id=?", (formal_revision_id,)).fetchone()
            if not revision:
                raise not_found_error(f"formal revision not found in {table}: {formal_revision_id}")
            if row["layer"] not in {"metadata", "source_record", "interpretation", "unit", "ontology"}:
                raise invalid_payload(f"unknown feedback layer: {row['layer']}")
            # B2: "corrected" must correspond to an actual revision distinct
            # from the feedback target — re-linking the target itself (however
            # well reviewed it already is) cannot turn "unchanged" into
            # "corrected"; a retained conclusion closes via retained_with_evidence.
            if formal_revision_id == row["target_id"]:
                raise revision_conflict(
                    f"formal revision {formal_revision_id} is the feedback target itself; "
                    "a correction requires an actual new revision (keep the original "
                    "conclusion via retained_with_evidence when it stands)")
            target_table = _FEEDBACK_TARGET_TABLES.get(row["layer"])
            if target_table:
                target = conn.execute(
                    f"SELECT * FROM {target_table} WHERE id=?", (row["target_id"],)).fetchone()
                if target is None:
                    raise not_found_error(f"feedback target missing: {row['target_id']}")
                if rev_layer == "ontology":
                    raise revision_conflict("ontology proposals do not attach to record feedback")
                revision_work = _revision_work_id(conn, table, revision)
                # B2: lineage — the revision must address the same work as the
                # feedback, whatever layer it lives on.
                if row["work_id"] and revision_work and row["work_id"] != revision_work:
                    raise revision_conflict(
                        f"revision {formal_revision_id} belongs to work "
                        f"{revision_work}, feedback targets work {row['work_id']}")
                # the revision must also actually descend from (or be) the
                # feedback's target record when they share a layer
                if target_table == table and row["layer"] == rev_layer:
                    in_lineage = self._record_in_lineage(conn, table, row["target_id"],
                                                         formal_revision_id)
                    if not in_lineage:
                        raise revision_conflict(
                            f"revision {formal_revision_id} does not descend from feedback "
                            f"target {row['target_id']} in {table}")
            if revision["validity_status"] not in (None, "active"):
                raise revision_conflict("cannot link a superseded/withdrawn revision")
            now = _now()
            conn.execute(
                "UPDATE research_feedback SET formal_revision_id=?,status='formal_revision_created',updated_at=? WHERE id=?",
                (formal_revision_id, now, feedback_id),
            )
            conn.commit()
            return {"feedback_id": feedback_id, "status": "formal_revision_created",
                    "formal_revision_id": formal_revision_id}

    def _record_in_lineage(self, conn: sqlite3.Connection, table: str,
                           ancestor_id: str, revision_id: str) -> bool:
        """True when revision_id is ancestor_id itself or descends from it via
        the supersedes chain (bounded walk; cycles are structurally excluded)."""
        current, seen = revision_id, set()
        id_column = "id"
        supersedes_column = "supersedes_id"
        while current:
            if current == ancestor_id:
                return True
            if current in seen:
                return False
            seen.add(current)
            row = conn.execute(
                f"SELECT {supersedes_column} FROM {table} WHERE {id_column}=?", (current,)
            ).fetchone()
            current = row[supersedes_column] if row else None
        return False

    def close_feedback(self, feedback_id: str, *, outcome: str,
                       resolution_note: str = "",
                       evidence: dict | None = None) -> dict:
        """Close feedback only when the claimed outcome is actually true (A4/B2).

        Distinguishable closure facts: ``corrected``/``partially_corrected``
        require a linked formal revision that descends from the target, has
        been agent-approved by an identified reviewer into the stable state —
        merely having submitted a revision does not equal "corrected".
        ``retained_with_evidence`` requires a non-empty resolution note plus
        machine-checkable evidence anchored in the target work's snapshot —
        a self-declared note alone cannot close a correction claim.
        """
        if outcome not in FEEDBACK_OUTCOMES:
            raise invalid_payload(f"outcome must be one of {FEEDBACK_OUTCOMES}")
        evidence_payload: dict | None = None
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM research_feedback WHERE id=?", (feedback_id,)).fetchone()
            if not row:
                raise not_found_error(feedback_id)
            if outcome in {"corrected", "partially_corrected"}:
                # 工单工作包 B：页面显示缺陷的“已纠正”关联实际修复与复验结果，
                # 不虚构论文内容修订，因此不要求研究记录修订链。
                if row["layer"] == "page_display":
                    if not resolution_note.strip():
                        raise revision_conflict(
                            "page_display 的 corrected 结论必须给出实际修复内容与复验结果说明")
                    evidence_payload = {"fix_note": resolution_note.strip()} if evidence is None \
                        else {**(evidence or {}), "fix_note": resolution_note.strip()}
                    now = _now()
                    conn.execute(
                        """UPDATE research_feedback SET status='closed',outcome=?,resolution_note=?,
                           resolution_evidence_json=?,updated_at=? WHERE id=?""",
                        (outcome, resolution_note.strip(),
                         json.dumps(evidence_payload, ensure_ascii=False) if evidence_payload else None,
                         now, feedback_id),
                    )
                    conn.commit()
                    return {"feedback_id": feedback_id, "status": "closed", "outcome": outcome,
                            "formal_revision_id": row["formal_revision_id"],
                            "evidence_recorded": bool(evidence_payload)}
                revision_id = row["formal_revision_id"]
                if not revision_id:
                    raise revision_conflict(
                        f"outcome {outcome} requires a linked formal revision")
                prefix = next((p for p in _REVISION_TABLES if revision_id.startswith(p + "-")), None)
                if not prefix:
                    raise revision_conflict(
                        f"linked formal revision {revision_id} is not a recognized revision id")
                table, rev_layer = _REVISION_TABLES[prefix]
                revision = conn.execute(
                    f"SELECT * FROM {table} WHERE id=?", (revision_id,)).fetchone()
                if not revision:
                    raise revision_conflict(
                        f"linked formal revision {revision_id} no longer exists")
                if revision_id == row["target_id"]:
                    raise revision_conflict(
                        f"outcome {outcome} cannot cite the feedback target itself as its "
                        "formal revision; a correction requires an actual new revision")
                if revision["agent_review_status"] != "approved" or \
                        revision["content_state"] != "stable" or \
                        revision["validity_status"] != "active":
                    raise revision_conflict(
                        f"outcome {outcome} requires the linked revision to be "
                        "agent-approved, stable and active (revision-submitted is not "
                        "verified-corrected)")
                # B2: the approval must carry a real reviewer identity — an
                # unidentified approval cannot turn a submission into a correction.
                approval = conn.execute(
                    """SELECT actor_type,actor_id FROM research_review_events
                       WHERE record_layer=? AND record_id=? AND decision='approved'
                       ORDER BY created_at DESC LIMIT 1""",
                    (rev_layer, revision_id),
                ).fetchone()
                if approval is None:
                    raise revision_conflict(
                        f"outcome {outcome} requires an approval event for {revision_id}")
                if not (approval["actor_id"] or "").strip():
                    raise revision_conflict(
                        f"the approval of {revision_id} has no reviewer identity; "
                        "an identified independent review is required before 'corrected'")
            elif outcome == "retained_with_evidence":
                if not resolution_note.strip():
                    raise invalid_payload(
                        "retained_with_evidence requires a non-empty resolution_note "
                        "explaining the retention evidence")
                if not evidence or not isinstance(evidence, dict):
                    raise invalid_payload(
                        "retained_with_evidence requires machine-checkable evidence "
                        "(snapshot-anchored quote) — a note alone cannot close it")
                anchor = self._validated_anchor(evidence)
                work_id = row["work_id"]
                if work_id:
                    self._anchor_belongs_to_work(
                        conn, anchor, work_id,
                        "retention evidence must come from the feedback target work's snapshot")
                evidence_payload = {**anchor, "note": resolution_note.strip()}
            else:
                evidence_payload = None
            now = _now()
            conn.execute(
                """UPDATE research_feedback SET status='closed',outcome=?,resolution_note=?,
                   resolution_evidence_json=?,updated_at=? WHERE id=?""",
                (outcome, resolution_note.strip(),
                 json.dumps(evidence_payload, ensure_ascii=False) if evidence_payload else None,
                 now, feedback_id),
            )
            conn.commit()
            return {"feedback_id": feedback_id, "status": "closed", "outcome": outcome,
                    "formal_revision_id": row["formal_revision_id"],
                    "evidence_recorded": bool(evidence_payload)}

    def metadata_head(self, *, work_id: str) -> dict | None:
        """当前元数据头（反馈面板定位 RMR 目标用；只读）。"""
        with closing(self.context.connect(read_only=True)) as conn:
            row = conn.execute(
                """SELECT id, batch_id, work_id, version, supersedes_id, validity_status,
                          content_state, agent_review_status, human_adoption_status
                   FROM research_metadata_records WHERE work_id=?
                   ORDER BY version DESC LIMIT 1""", (work_id,)).fetchone()
            return dict(row) if row else None

    def list_feedback(self, *, work_id: str | None = None, layer: str | None = None,
                      target_id: str | None = None, status: str | None = None) -> list[dict]:
        with closing(self.context.connect(read_only=True)) as conn:
            chain: list[str] = []
            if target_id and layer and layer in _FEEDBACK_TARGET_TABLES and layer != "ontology":
                # B9：质疑随记录链持续可见。基线推进（supersede）后，祖先记录上的
                # 质疑与其闭环回显不得从查询中消失，否则“最终结果以下方回显为准”
                # 在修订采纳后会失真。
                table = _FEEDBACK_TARGET_TABLES[layer]
                seen: set[str] = {target_id}
                cursor: str | None = target_id
                while cursor:
                    row = conn.execute(
                        f"SELECT supersedes_id FROM {table} WHERE id=?", (cursor,)).fetchone()
                    ancestor = row["supersedes_id"] if row else None
                    if not ancestor or ancestor in seen:
                        break
                    seen.add(ancestor)
                    chain.append(ancestor)
                    cursor = ancestor
            if chain:
                placeholders = ",".join("?" for _ in chain)
                where = [f"target_id IN (?,{placeholders})"]
                params: list = [target_id, *chain]
                for column, value in (("work_id", work_id), ("layer", layer), ("status", status)):
                    if value:
                        where.append(f"{column}=?")
                        params.append(value)
                rows = [dict(r) for r in conn.execute(
                    f"""SELECT * FROM research_feedback
                        WHERE {' AND '.join(where)} ORDER BY created_at, id""", params)]
                for row in rows:
                    row["on_ancestor_record"] = row["target_id"] != target_id
                return rows
            where, params = [], []
            for column, value in (("work_id", work_id), ("layer", layer),
                                  ("target_id", target_id), ("status", status)):
                if value:
                    where.append(f"{column}=?")
                    params.append(value)
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            return [dict(r) for r in conn.execute(
                f"SELECT * FROM research_feedback{clause} ORDER BY created_at, id", params
            )]

    def _link_feedback(self, conn: sqlite3.Connection, feedback_id: str | None,
                       revision_id: str, now: str) -> None:
        if not feedback_id:
            return
        row = conn.execute("SELECT status FROM research_feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row:
            raise not_found_error(feedback_id)
        if row["status"] == "closed":
            raise revision_conflict("feedback already closed")
        conn.execute(
            "UPDATE research_feedback SET formal_revision_id=?,status='formal_revision_created',updated_at=? WHERE id=?",
            (revision_id, now, feedback_id),
        )

    # ----- stable upgrade: work metadata queue / immutable re-review / profile -----

    _METADATA_TASK_STATUSES = ("absent", "pending", "conflict", "stable", "excluded")
    _METADATA_TASK_EXPLICIT = ("excluded", "conflict")

    def _derive_metadata_task_status(self, conn: sqlite3.Connection,
                                     work_id: str, persisted: str | None) -> tuple[str, dict | None]:
        """Live A-queue status for one work.

        ``excluded``/``conflict`` are persisted decisions with reasons and stay
        until explicitly cleared; every other status is derived from the work's
        current A head so the queue can never drift from the record chain
        (a stable work never re-enters the production queue, and an approved
        head is idempotently reusable instead of re-produced).
        """
        if persisted in self._METADATA_TASK_EXPLICIT:
            return persisted, None
        head = current_metadata_head(conn, work_id)
        if head is None:
            return "absent", None
        if (head["agent_review_status"] == "approved"
                and head["content_state"] == "stable"):
            return "stable", head
        return "pending", head

    def ensure_metadata_task(self, *, work_id: str, reason: str,
                             operation_id: str) -> dict:
        if not work_exists(self.context, work_id):
            raise not_found_error(f"unknown work_id {work_id}")
        if not operation_id.strip() or not reason.strip():
            raise invalid_payload("operation_id and reason are required")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            by_operation = conn.execute(
                "SELECT * FROM research_metadata_tasks WHERE operation_id=?",
                (operation_id,)).fetchone()
            by_work = conn.execute(
                "SELECT * FROM research_metadata_tasks WHERE work_id=?",
                (work_id,)).fetchone()
            if by_operation and by_work and by_operation["id"] != by_work["id"]:
                raise revision_conflict(
                    "operation_id already belongs to another work's metadata task")
            existing = by_work
            status, head = self._derive_metadata_task_status(
                conn, work_id, existing["status"] if existing else None)
            now = _now()
            head_id = head["id"] if head else (
                existing["metadata_record_id"] if existing else None)
            if existing:
                conn.execute(
                    """UPDATE research_metadata_tasks SET status=?,reason=?,
                       metadata_record_id=?,operation_id=?,updated_at=? WHERE id=?""",
                    (status, reason, head_id, operation_id, now, existing["id"]))
                task_id, created = existing["id"], False
            else:
                task_id, created = _id("RMT"), True
                conn.execute(
                    """INSERT INTO research_metadata_tasks
                       (id,work_id,status,reason,metadata_record_id,operation_id,
                        created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (task_id, work_id, status, reason, head_id, operation_id, now, now))
            conn.commit()
        return {"task_id": task_id, "work_id": work_id, "status": status,
                "metadata_record_id": head_id, "created": created,
                "rule": "absent/pending/stable 从当前 A 头实时推导；excluded/conflict 为显式决策，需理由"}

    def transition_metadata_task(self, task_id: str, *, status: str, reason: str,
                                 actor_id: str) -> dict:
        """Explicit exclusion/conflict decisions (and their clearance).

        Exclusion and merge-out must carry a reason (WF-013: 排除/归并有理由);
        reactivating clears the explicit state back to live derivation.
        """
        if status not in self._METADATA_TASK_STATUSES:
            raise invalid_payload(f"invalid metadata task status: {status}")
        if not reason.strip() or not actor_id.strip():
            raise invalid_payload("reason and actor_id are required")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_metadata_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise not_found_error(task_id)
            if status not in self._METADATA_TASK_EXPLICIT and status != "pending":
                raise invalid_payload(
                    "only excluded/conflict decisions and pending reactivation "
                    "are explicit transitions; other statuses are derived from the A head")
            derived, head = self._derive_metadata_task_status(
                conn, row["work_id"], status if status in self._METADATA_TASK_EXPLICIT else None)
            now = _now()
            history = json.loads(row["reason"] or "[]") if row["reason"].startswith("[") else []
            history.append({"from": row["status"], "to": derived, "reason": reason,
                            "actor_id": actor_id, "at": now})
            conn.execute(
                """UPDATE research_metadata_tasks SET status=?,reason=?,metadata_record_id=?,
                   updated_at=? WHERE id=?""",
                (derived, json.dumps(history, ensure_ascii=False),
                 head["id"] if head else row["metadata_record_id"], now, task_id))
            conn.commit()
        return {"task_id": task_id, "work_id": row["work_id"], "status": derived,
                "reason_history": history}

    def list_metadata_tasks(self, *, status: str | None = None) -> dict:
        if status and status not in self._METADATA_TASK_STATUSES:
            raise invalid_payload("invalid metadata task status")
        with closing(self.context.connect(read_only=True)) as conn:
            rows = conn.execute(
                "SELECT * FROM research_metadata_tasks ORDER BY updated_at,work_id").fetchall()
            items = []
            for row in rows:
                derived, head = self._derive_metadata_task_status(
                    conn, row["work_id"], row["status"])
                item = dict(row)
                item["status"] = derived
                item["persisted_status"] = row["status"]
                item["metadata_record_id"] = head["id"] if head else row["metadata_record_id"]
                items.append(item)
        if status:
            items = [item for item in items if item["status"] == status]
        return {"status": status, "items": items,
                "rule": "状态实时推导自 A 头；excluded/conflict 保留显式决策"}

    def metadata_worklist(self) -> dict:
        """Read-only Work-level A inventory, independent of research batches.

        A catalog Work appears without a cross-database ingestion write.  A
        successful parse makes it actionable; explicit queue decisions and A
        heads are read live so refreshing never creates duplicate tasks.
        """
        if not catalog_available(self.context):
            raise dependency_unavailable("catalog works table unavailable")
        with closing(catalog_conn(self.context, read_only=True)) as catalog:
            work_columns = {r[1] for r in catalog.execute("PRAGMA table_info(works)")}
            select = ["id", "title"] + [c for c in ("read_status", "ingestion_state", "parse_status")
                                         if c in work_columns]
            works = [dict(r) for r in catalog.execute(
                f"SELECT {','.join(select)} FROM works ORDER BY id")]
            parse_runs = {}
            if catalog.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='literature_parse_runs'").fetchone():
                for run in catalog.execute(
                    """SELECT id,work_id,source_file_id,source_path,content_md_path,
                              content_json_path,output_dir,finished_at,started_at
                       FROM literature_parse_runs
                       WHERE status='succeeded' AND COALESCE(content_md_path,'')<>''
                       ORDER BY COALESCE(finished_at,started_at) DESC,id DESC"""):
                    parse_runs.setdefault(run["work_id"], dict(run))
            # RWEB-02: fixed-version storage locators for the materials an Agent
            # work order names. PDF binds to the source-file identity, md/json
            # to the parse-run identity; versions come from the live registry,
            # never guessed.
            worklist_assets = {}
            if parse_runs and catalog.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='storage_bindings'").fetchone():
                asset_ids = sorted({r["id"] for r in parse_runs.values()} |
                                   {r["source_file_id"] for r in parse_runs.values()})
                placeholders = ",".join("?" * len(asset_ids))
                for binding in catalog.execute(
                        f"SELECT identity,role,version,sha256,bytes FROM storage_bindings "
                        f"WHERE identity IN ({placeholders}) AND role IN ('pdf','md','json')", asset_ids):
                    worklist_assets.setdefault(binding["identity"], {})[binding["role"]] = {
                        "identity": binding["identity"], "role": binding["role"],
                        "version": binding["version"], "sha256": binding["sha256"],
                        "bytes": binding["bytes"]}
        with closing(self.context.connect(read_only=True)) as conn:
            tasks = {r["work_id"]: dict(r) for r in conn.execute(
                "SELECT * FROM research_metadata_tasks")}
            heads = {}
            for row in conn.execute(
                """SELECT id,work_id,version,agent_review_status,content_state,
                          validity_status,human_adoption_status,batch_id,created_at
                   FROM research_metadata_records ORDER BY version DESC,created_at DESC,id DESC"""):
                heads.setdefault(row["work_id"], dict(row))
            feedback = {r["work_id"]: r["n"] for r in conn.execute(
                """SELECT work_id,COUNT(*) n FROM research_feedback
                   WHERE layer='metadata' AND status<>'closed' GROUP BY work_id""")}
        items = []
        counts = {key: 0 for key in ("waiting_parse", "absent", "pending", "stable", "excluded", "conflict", "quarantined")}
        for work in works:
            work_id = work["id"]
            task = tasks.get(work_id)
            head = heads.get(work_id)
            parse = parse_runs.get(work_id)
            # Do not offer missing files as usable material to an Agent.
            parse_ready = bool(parse and material_ready(parse["content_md_path"]))
            if work.get("read_status") == "quarantined":
                state = "quarantined"
            elif task and task["status"] in self._METADATA_TASK_EXPLICIT:
                state = task["status"]
            elif head and head["agent_review_status"] == "approved" and head["content_state"] == "stable" and head["validity_status"] == "active":
                state = "stable"
            elif head:
                state = "pending"
            else:
                state = "absent" if parse_ready else "waiting_parse"
            counts[state] += 1
            item_assets = None
            if parse:
                item_assets = {"pdf": worklist_assets.get(parse["source_file_id"], {}).get("pdf"),
                               "md": worklist_assets.get(parse["id"], {}).get("md"),
                               "json": worklist_assets.get(parse["id"], {}).get("json")}
            items.append({**work, "status": state, "parse_ready": parse_ready,
                          "parse": parse, "metadata_head": head,
                          "assets": item_assets,
                          "task_id": task["id"] if task else None,
                          "task_reason": task["reason"] if task else None,
                          "open_feedback_count": feedback.get(work_id, 0)})
        return {"items": items, "counts": counts, "total": len(items),
                "rule": "按 Work 自动呈现；解析成功且 Markdown 文件可用时可开展 A；稳定头复用，排除/冲突保留显式决定"}

    def metadata_work_detail(self, work_id: str) -> dict:
        """All A versions and open/closed feedback for human inspection."""
        if not work_exists(self.context, work_id):
            raise not_found_error(work_id)
        with closing(self.context.connect(read_only=True)) as conn:
            records = []
            for row in conn.execute(
                "SELECT * FROM research_metadata_records WHERE work_id=? ORDER BY version DESC,id DESC",
                (work_id,)):
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                records.append(item)
            feedback = [dict(row) for row in conn.execute(
                """SELECT id,target_id,target_version,explicit_claim,detail,status,outcome,
                          formal_revision_id,resolution_note,created_at,updated_at
                   FROM research_feedback WHERE work_id=? AND layer='metadata'
                   ORDER BY created_at DESC,id DESC""", (work_id,))]
        return {"work_id": work_id, "records": records, "feedback": feedback,
                "current_head_id": records[0]["id"] if records else None}

    def append_stable_rereview(self, layer: str, record_id: str, *, actor_id: str,
                               event_key: str, basis: dict, scope: dict | None = None,
                               note: str = "", decision: str = "approved") -> dict:
        """Append a REAL re-review event onto an already stable record.

        PLATFORM-001: the event pins reviewer, record version, scope, basis,
        time and an idempotency key.  Replaying the same key adds no row; a key
        that belongs to another target fails closed.  The record's state and
        the bibliographic projection are never touched — a negative re-review
        is an audit signal whose remedy is a formal revision, not a state edit.
        """
        tables = {"metadata": "research_metadata_records", "unit": "research_units",
                  "source_record": "research_source_records",
                  "interpretation": "research_interpretations"}
        table = tables.get(layer)
        if not table:
            raise invalid_payload(f"unsupported record layer: {layer}")
        if decision not in ("approved", "rejected"):
            raise invalid_payload("stable re-review decision must be approved or rejected")
        if not actor_id.strip() or not event_key.strip() or not isinstance(basis, dict) or not basis:
            raise invalid_payload("actor_id, event_key and non-empty basis are required")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            replay = conn.execute(
                "SELECT * FROM research_review_events WHERE event_key=?", (event_key,)).fetchone()
            if replay:
                if (replay["record_layer"] != layer or replay["record_id"] != record_id
                        or replay["decision"] != decision):
                    raise revision_conflict(
                        "event_key already belongs to another review event "
                        "(different target or decision); use a new key")
                conn.commit()
                return {"event_id": replay["id"], "record_id": record_id,
                        "record_version": replay["record_version"], "replayed": True,
                        "decision": decision, "state_unchanged": True}
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise not_found_error(record_id)
            if row["agent_review_status"] != "approved" or row["content_state"] != "stable":
                raise invalid_payload("re-review append requires an already approved stable record")
            _require_reviewer_identity(decision, actor_id, row["submitted_by"],
                                       action=f"{layer} stable re-review")
            event_id, now = _id("RR"), _now()
            conn.execute(
                """INSERT INTO research_review_events
                   (id,record_layer,record_id,actor_type,actor_id,decision,note,scope_json,
                    record_version,basis_json,event_key,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, layer, record_id, "agent", actor_id, decision, note,
                 json.dumps(scope, ensure_ascii=False) if scope is not None else None,
                 row["version"], json.dumps(basis, ensure_ascii=False), event_key, now))
            conn.commit()
        return {"event_id": event_id, "record_id": record_id,
                "record_version": row["version"], "replayed": False,
                "decision": decision,
                "state_unchanged": True, "projection_republished": False,
                "note": "复审事件只追加留痕；记录状态与书目投影不变，负面结论的正式处置走反馈/修订链"}

    def preflight_work(self, work_id: str) -> dict:
        """Scheduling hints for one work — never an automatic decision.

        Returns historical metadata versions, open AND closed feedback, active
        batch items and the fixed snapshots a new task would consume.  The
        caller decides; the platform does not auto-schedule on this response.
        """
        if not work_exists(self.context, work_id):
            raise not_found_error(work_id)
        with closing(self.context.connect(read_only=True)) as conn:
            source_ids = [r[0] for r in conn.execute(
                "SELECT id FROM research_sources WHERE work_id=?", (work_id,))]
            active_items = []
            if source_ids:
                marks = ",".join("?" for _ in source_ids)
                active_items = [dict(r) for r in conn.execute(
                    f"""SELECT bi.id,bi.batch_id,bi.source_id,bi.status,bi.worker_owner,
                               bi.lease_expires_at,bi.attempt,b.name AS batch_name
                         FROM research_batch_items bi
                         JOIN research_batches b ON b.id=bi.batch_id
                         WHERE bi.source_id IN ({marks}) AND bi.status IN ('planned','running')
                         ORDER BY bi.updated_at""", source_ids)]
            feedback_open = [dict(r) for r in conn.execute(
                """SELECT id,layer,target_id,target_version,explicit_claim,status,created_at
                   FROM research_feedback WHERE work_id=? AND status!='closed'
                   ORDER BY created_at""", (work_id,))]
            feedback_closed = [dict(r) for r in conn.execute(
                """SELECT id,layer,target_id,target_version,explicit_claim,status,outcome,
                          resolution_note,created_at,updated_at
                   FROM research_feedback WHERE work_id=? AND status='closed'
                   ORDER BY updated_at DESC LIMIT 20""", (work_id,))]
            history = [dict(r) for r in conn.execute(
                """SELECT id,batch_id,work_id,version,agent_review_status,content_state,
                          validity_status,created_at FROM research_metadata_records
                   WHERE work_id=? ORDER BY version""", (work_id,))]
            snapshots = [dict(r) for r in conn.execute(
                """SELECT s.id AS source_id,s.citation_key,t.id AS snapshot_id,
                          t.version,t.content_sha256,t.parse_quality,t.created_at
                   FROM research_sources s LEFT JOIN research_text_snapshots t
                     ON t.source_id=s.id
                   WHERE s.work_id=? ORDER BY s.id,t.version""", (work_id,))]
            stable_basis = [dict(r) for r in conn.execute(
                """SELECT DISTINCT i.batch_id, i.id AS interpretation_id, i.version,
                          i.scope_json, i.content_state
                   FROM research_interpretations i
                   JOIN research_sources s ON s.id=i.source_id
                   WHERE s.work_id=? AND i.validity_status='active'
                     AND i.agent_review_status='approved' AND i.content_state='stable'
                   ORDER BY i.batch_id""", (work_id,))]
        return {"work_id": work_id,
                "open_feedback": feedback_open, "closed_feedback_recent": feedback_closed,
                "active_batch_items": active_items, "metadata_history": history,
                "snapshots": snapshots, "stable_interpretation_basis": stable_basis,
                "safe_to_schedule": not feedback_open and not active_items,
                "rule": "提示不构成自动决定；调度决策由操作方依据本响应显式作出"}

    # ----- PLATFORM-003: batch-free work research profile -----

    def work_research_profile(self, work_id: str) -> dict:
        """Read-only whole-work aggregation across every batch and version.

        Shows the A chain even when the work has no research source, every
        source/snapshot, all-batch C/D versions with their scopes, references,
        reuse bindings, feedback, adoption and the recommended baselines with
        their eligibility reasons.  Multiple legitimate scopes are listed side
        by side — nothing is merged or time-picked silently.
        """
        if not work_exists(self.context, work_id):
            raise not_found_error(work_id)
        with closing(self.context.connect(read_only=True)) as conn:
            catalog = catalog_work_identity(self.context, work_id)
            metadata_rows = [dict(r) for r in conn.execute(
                """SELECT id,batch_id,version,supersedes_id,agent_review_status,
                          human_adoption_status,validity_status,content_state,
                          submitted_by,created_at
                   FROM research_metadata_records WHERE work_id=? ORDER BY version""",
                (work_id,))]
            head = current_metadata_head(conn, work_id)
            approved_stable = current_metadata_head(conn, work_id, approved_stable_only=True)
            task_row = conn.execute(
                "SELECT * FROM research_metadata_tasks WHERE work_id=?", (work_id,)).fetchone()
            task = None
            if task_row:
                derived_status, head_row = self._derive_metadata_task_status(
                    conn, work_id, task_row["status"])
                task = {"task_id": task_row["id"], "status": derived_status,
                        "persisted_status": task_row["status"]}
            sources = [dict(r) for r in conn.execute(
                "SELECT * FROM research_sources WHERE work_id=? ORDER BY id", (work_id,))]
            snapshots: dict[str, list] = {}
            source_records: list[dict] = []
            interpretations: list[dict] = []
            for source in sources:
                snapshots[source["id"]] = [dict(r) for r in conn.execute(
                    """SELECT id,version,content_sha256,parse_exists,parse_quality,created_at
                       FROM research_text_snapshots WHERE source_id=? ORDER BY version""",
                    (source["id"],))]
                for row in conn.execute(
                        """SELECT r.id,r.batch_id,r.version,r.validity_status,
                                  r.agent_review_status,r.human_adoption_status,
                                  r.content_state,r.scope_json,r.snapshot_id,r.created_at
                           FROM research_source_records r WHERE r.source_id=? ORDER BY r.version""",
                        (source["id"],)):
                    record = dict(row)
                    record["scope"] = json.loads(record.pop("scope_json") or "null")
                    source_records.append(record)
                for row in conn.execute(
                        """SELECT i.id,i.source_id,i.batch_id,i.version,i.source_record_id,
                                  i.source_metadata_record_id,i.validity_status,
                                  i.agent_review_status,i.human_adoption_status,
                                  i.content_state,i.scope_json,i.created_at
                           FROM research_interpretations i WHERE i.source_id=? ORDER BY i.version""",
                        (source["id"],)):
                    interp = dict(row)
                    interp["scope"] = json.loads(interp.pop("scope_json") or "null")
                    interp["metadata_dependency"] = assess_metadata_dependency(
                        conn, work_id=work_id,
                        pinned_record_id=interp["source_metadata_record_id"])
                    interpretations.append(interp)
            reference_counts = {r[0]: r[1] for r in conn.execute(
                """SELECT match_status, COUNT(*) FROM research_reference_objects
                   WHERE citing_work_id=? GROUP BY match_status""", (work_id,))}
            reference_lifecycle = {r[0]: r[1] for r in conn.execute(
                """SELECT lifecycle_status, COUNT(*) FROM research_reference_objects
                   WHERE citing_work_id=? GROUP BY lifecycle_status""", (work_id,))}
            source_id_list = [s["id"] for s in sources]
            incoming_bindings: list[dict] = []
            if source_id_list:
                marks = ",".join("?" for _ in source_id_list)
                incoming_bindings = [dict(r) for r in conn.execute(
                    f"""SELECT rb.*, b.name AS target_batch_name
                        FROM research_reuse_bindings rb
                        JOIN research_batch_items bi ON bi.id=rb.batch_item_id
                        JOIN research_batches b ON b.id=rb.target_batch_id
                        WHERE bi.source_id IN ({marks})""", source_id_list)]
            outgoing_bindings = [dict(r) for r in conn.execute(
                """SELECT rb.* FROM research_reuse_bindings rb
                   WHERE rb.source_record_id IN
                     (SELECT id FROM research_source_records WHERE source_id IN
                       (SELECT id FROM research_sources WHERE work_id=?))""", (work_id,))]
            feedback_open = [dict(r) for r in conn.execute(
                """SELECT id,layer,target_id,explicit_claim,status,created_at
                   FROM research_feedback WHERE work_id=? AND status!='closed'
                   ORDER BY created_at""", (work_id,))]
            adoption = {}
            for label, rows in (("metadata", metadata_rows), ("source_record", source_records),
                                ("interpretation", interpretations)):
                adoption[label] = {
                    state: sum(1 for r in rows if r.get("human_adoption_status") == state)
                    for state in ("pending", "adopted", "rejected")}
            # Recommended baselines: per (source, scope, batch) list every
            # approved-stable D with its dependency eligibility.  Legitimate
            # scopes stand side by side; nothing is auto-merged or time-picked.
            baselines: list[dict] = []
            for interp in interpretations:
                if not (interp["validity_status"] == "active"
                        and interp["agent_review_status"] == "approved"
                        and interp["content_state"] == "stable"):
                    continue
                dep = interp["metadata_dependency"]
                baselines.append({
                    "source_id": interp["source_id"],
                    "interpretation_id": interp["id"], "batch_id": interp["batch_id"],
                    "version": interp["version"], "scope": interp["scope"],
                    "dependency_usable": dep["usable"],
                    "dependency_status": dep["status"],
                    "eligible_recommended": bool(dep["usable"]),
                    "reason": (None if dep["usable"] else dep.get("reason")),
                })
        return {
            "work_id": work_id,
            "catalog_identity": catalog,
            "metadata": {"records": metadata_rows,
                         "head_record_id": head["id"] if head else None,
                         "approved_stable_head_id": approved_stable["id"] if approved_stable else None,
                         "queue_task": task},
            "sources": [{"source": {k: s[k] for k in s if k != "id"}, "source_id": s["id"],
                         "snapshots": snapshots.get(s["id"], [])} for s in sources],
            "source_records": source_records,
            "interpretations": interpretations,
            "references": {"by_match_status": reference_counts,
                           "by_lifecycle": reference_lifecycle},
            "reuse_bindings": {"incoming": incoming_bindings, "outgoing": outgoing_bindings},
            "feedback": {"open": feedback_open},
            "human_adoption": adoption,
            "recommended_baselines": baselines,
            "baseline_rule": "按 (source, scope, batch) 并列列出全部合法稳定 D；"
                             "推荐资格=依赖可用，多个合法范围不合并、不按时间强选",
        }

    # ----- EXEC-001: formal cross-batch reuse bindings -----

    def preflight_reuse(self, *, batch_id: str, source_id: str) -> dict:
        """Open feedback, active tasks and prior achievements for one item's work."""
        with closing(self.context.connect(read_only=True)) as conn:
            item = conn.execute(
                """SELECT bi.*, s.work_id FROM research_batch_items bi
                   JOIN research_sources s ON s.id=bi.source_id
                   WHERE bi.batch_id=? AND bi.source_id=?""", (batch_id, source_id)
            ).fetchone()
            if not item:
                raise not_found_error(f"batch item {batch_id}/{source_id}")
            work_id = item["work_id"]
            return self._work_achievement_snapshot(conn, work_id)

    def _work_achievement_snapshot(self, conn: sqlite3.Connection, work_id: str) -> dict:
        prior_c = [dict(r) for r in conn.execute(
            """SELECT r.id,r.batch_id,r.version,r.validity_status,r.agent_review_status,
                      r.content_state,r.snapshot_id
               FROM research_source_records r JOIN research_sources s ON s.id=r.source_id
               WHERE s.work_id=? ORDER BY r.created_at""", (work_id,))]
        prior_d = [dict(r) for r in conn.execute(
            """SELECT i.id,i.batch_id,i.version,i.source_record_id,
                      i.source_metadata_record_id,i.validity_status,
                      i.agent_review_status,i.content_state
               FROM research_interpretations i JOIN research_sources s ON s.id=i.source_id
               WHERE s.work_id=? ORDER BY i.created_at""", (work_id,))]
        open_feedback = [dict(r) for r in conn.execute(
            """SELECT id,layer,target_id,explicit_claim,status FROM research_feedback
               WHERE work_id=? AND status!='closed'""", (work_id,))]
        active_items = [dict(r) for r in conn.execute(
            """SELECT bi.batch_id,bi.source_id,bi.status,bi.worker_owner,bi.lease_expires_at
               FROM research_batch_items bi JOIN research_sources s ON s.id=bi.source_id
               WHERE s.work_id=? AND bi.status IN ('planned','running')""", (work_id,))]
        return {"work_id": work_id, "prior_source_records": prior_c,
                "prior_interpretations": prior_d, "open_feedback": open_feedback,
                "active_items": active_items}

    def bind_reuse(self, *, batch_id: str, source_id: str, source_record_id: str,
                   interpretation_id: str | None, metadata_record_id: str,
                   reason: str, operation_id: str, actor_id: str) -> dict:
        """Bind a batch item to an EXISTING foreign-batch result (EXEC-001).

        The binding pins the exact C/D/A record ids, versions, snapshot,
        release and reason with an idempotent operation id.  Nothing is
        copied, no pointer is silently re-aimed, and failed/permanent-running
        sources cannot masquerade as completion: the pinned C must be an
        active, approved, stable record and the A dependency must be usable.
        """
        if not reason.strip() or not operation_id.strip() or not actor_id.strip():
            raise invalid_payload("reason, operation_id and actor_id are required")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            replay = conn.execute(
                "SELECT * FROM research_reuse_bindings WHERE operation_id=?",
                (operation_id,)).fetchone()
            item = conn.execute(
                """SELECT bi.*, s.work_id FROM research_batch_items bi
                   JOIN research_sources s ON s.id=bi.source_id
                   WHERE bi.batch_id=? AND bi.source_id=?""", (batch_id, source_id)
            ).fetchone()
            if not item:
                raise not_found_error(f"batch item {batch_id}/{source_id}")
            if replay:
                if replay["batch_item_id"] != item["id"]:
                    raise revision_conflict(
                        "operation_id already belongs to another batch item's reuse binding")
                conn.commit()
                return {"binding_id": replay["id"],
                        "batch_item_id": replay["batch_item_id"],
                        "target_batch_id": replay["target_batch_id"],
                        "source_batch_id": replay["source_batch_id"],
                        "source_record_id": replay["source_record_id"],
                        "interpretation_id": replay["interpretation_id"],
                        "metadata_record_id": replay["metadata_record_id"],
                        "snapshot_id": replay["snapshot_id"],
                        "status": replay["status"], "operation_id": operation_id,
                        "replayed": True,
                        "note": "同 operation_id 重放返回既有绑定，不产生新行"}
            active_binding = conn.execute(
                """SELECT * FROM research_reuse_bindings
                   WHERE batch_item_id=? AND status='active'""", (item["id"],)).fetchone()
            if active_binding:
                raise revision_conflict(
                    f"batch item already has an active reuse binding "
                    f"{active_binding['id']}; supersede it explicitly first")
            if item["status"] == "submitted":
                raise revision_conflict(
                    "batch item is already submitted; reuse binding applies to "
                    "open items only")
            if item["status"] not in ("planned", "running", "failed", "stale"):
                raise invalid_payload(
                    f"batch item status {item['status']!r} cannot be closed by a "
                    "reuse binding")
            now_iso = _now()
            lease_alive = (item["worker_owner"] and item["lease_expires_at"]
                           and item["lease_expires_at"] > now_iso)
            record = conn.execute(
                "SELECT * FROM research_source_records WHERE id=?", (source_record_id,)).fetchone()
            if not record:
                raise not_found_error(source_record_id)
            source_of_record = conn.execute(
                "SELECT * FROM research_sources WHERE id=?", (record["source_id"],)).fetchone()
            if source_of_record["work_id"] != item["work_id"]:
                raise invalid_payload(
                    f"source record {source_record_id} belongs to work "
                    f"{source_of_record['work_id']}, not the item's work {item['work_id']}")
            if not (record["validity_status"] == "active"
                    and record["agent_review_status"] == "approved"
                    and record["content_state"] == "stable"):
                raise invalid_payload(
                    "reuse source record must be active, approved and stable; "
                    "failed or pending C cannot complete an item "
                    f"(state: {record['validity_status']}/"
                    f"{record['agent_review_status']}/{record['content_state']})")
            record_batch = conn.execute(
                "SELECT id FROM research_batches WHERE id=?", (record["batch_id"],)).fetchone()
            if not record_batch:
                raise not_found_error(record["batch_id"])
            if record["batch_id"] == batch_id:
                raise invalid_payload(
                    "reuse binds a CROSS-batch result; same-batch completion goes "
                    "through the normal submit path")
            interpretation = None
            if interpretation_id:
                interpretation = conn.execute(
                    "SELECT * FROM research_interpretations WHERE id=?",
                    (interpretation_id,)).fetchone()
                if not interpretation:
                    raise not_found_error(interpretation_id)
                if interpretation["source_record_id"] != source_record_id:
                    raise invalid_payload(
                        "interpretation does not bind the pinned source record")
                if not (interpretation["validity_status"] == "active"
                        and interpretation["agent_review_status"] == "approved"
                        and interpretation["content_state"] == "stable"):
                    raise invalid_payload(
                        "reuse interpretation must be active, approved and stable")
            dependency = assess_metadata_dependency(
                conn, work_id=item["work_id"], pinned_record_id=metadata_record_id)
            if not dependency["usable"]:
                raise invalid_payload(
                    f"reuse metadata dependency not usable: "
                    f"{dependency.get('reason') or dependency['status']}")
            snapshot_id = _row_value(record, "snapshot_id")
            if not snapshot_id:
                raise invalid_payload("source record carries no fixed snapshot id")
            release_id = _row_value(record, "release_id")
            validation = {
                "identity": "source record work == item work",
                "item_from_status": item["status"],
                "source_record_state": "active/approved/stable",
                "interpretation_state": (None if not interpretation_id else
                                         "active/approved/stable"),
                "metadata_dependency": dependency,
                "snapshot_id": snapshot_id, "release_id": release_id,
                "lease_check": "no live foreign lease" if not lease_alive else "live lease held",
                "validated_at": now_iso, "validated_by": actor_id,
            }
            binding_id = _id("RRB")
            conn.execute(
                """INSERT INTO research_reuse_bindings
                   (id,batch_item_id,target_batch_id,source_batch_id,source_record_id,
                    interpretation_id,metadata_record_id,snapshot_id,release_id,reason,
                    validation_json,status,operation_id,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?, 'active', ?, ?, ?)""",
                (binding_id, item["id"], batch_id, record["batch_id"], source_record_id,
                 interpretation_id, metadata_record_id, snapshot_id, release_id, reason,
                 json.dumps(validation, ensure_ascii=False), operation_id, now_iso, now_iso))
            conn.execute(
                """UPDATE research_batch_items SET status='submitted', updated_at=?
                   WHERE id=?""", (now_iso, item["id"]))
            conn.commit()
        return {"binding_id": binding_id, "batch_item_id": item["id"],
                "target_batch_id": batch_id, "source_batch_id": record["batch_id"],
                "source_record_id": source_record_id,
                "interpretation_id": interpretation_id,
                "metadata_record_id": metadata_record_id,
                "snapshot_id": snapshot_id, "release_id": release_id,
                "status": "active", "operation_id": operation_id,
                "validation": validation, "replayed": False,
                "note": "绑定不复制 C/D，不改动原批记录；item 状态置 submitted 表示调度闭环，"
                        "work 可用覆盖以 usable 口径单独报告"}

    def reuse_drift(self, batch_id: str) -> list[dict]:
        """Live drift of a batch's reuse bindings — review hints, never re-points."""
        with closing(self.context.connect(read_only=True)) as conn:
            rows = conn.execute(
                """SELECT rb.*, bi.source_id FROM research_reuse_bindings rb
                   JOIN research_batch_items bi ON bi.id=rb.batch_item_id
                   WHERE rb.target_batch_id=?""", (batch_id,)).fetchall()
            drift: list[dict] = []
            for row in rows:
                entry = {"binding_id": row["id"], "source_id": row["source_id"],
                         "status": row["status"], "drift": False, "details": []}
                source = conn.execute(
                    """SELECT work_id FROM research_sources WHERE id=?""",
                    (row["source_id"],)).fetchone()
                work_id = source["work_id"] if source else None
                head_c = conn.execute(
                    """SELECT id FROM research_source_records
                       WHERE source_id=? AND validity_status='active'
                       ORDER BY version DESC LIMIT 1""",
                    (row["source_id"],)).fetchone()
                if head_c and head_c["id"] != row["source_record_id"]:
                    entry["drift"] = True
                    entry["details"].append({
                        "kind": "source_record_head_changed",
                        "pinned": row["source_record_id"], "current": head_c["id"],
                        "action": "review_required"})
                if row["interpretation_id"]:
                    pinned_d = conn.execute(
                        "SELECT source_record_id FROM research_interpretations WHERE id=?",
                        (row["interpretation_id"],)).fetchone()
                    if not pinned_d:
                        entry["drift"] = True
                        entry["details"].append({"kind": "interpretation_missing",
                                                 "action": "review_required"})
                if work_id:
                    dependency = assess_metadata_dependency(
                        conn, work_id=work_id, pinned_record_id=row["metadata_record_id"])
                    if not dependency["usable"]:
                        entry["drift"] = True
                        entry["details"].append({
                            "kind": "metadata_dependency", "action": "review_required",
                            "assessment": dependency})
                if entry["drift"]:
                    entry["review_required"] = True
                    drift.append(entry)
            return drift

    def batch_progress(self, batch_id: str) -> dict:
        """Separate reporting: item progress vs work usable coverage vs adoption.

        EXEC-001: an item completed by reuse is a scheduling closure, NOT
        evidence of new production; usable coverage comes from the canonical
        usable-basis contract, and human adoption is its own column.
        """
        from .research_service import ResearchService
        with closing(self.context.connect(read_only=True)) as conn:
            if not conn.execute(
                    "SELECT 1 FROM research_batches WHERE id=?", (batch_id,)).fetchone():
                raise not_found_error(batch_id)
            items = [dict(r) for r in conn.execute(
                "SELECT * FROM research_batch_items WHERE batch_id=?", (batch_id,))]
            bound_items = {r["batch_item_id"] for r in conn.execute(
                """SELECT batch_item_id FROM research_reuse_bindings
                   WHERE target_batch_id=? AND status='active'""", (batch_id,))}
            item_progress = {"total": len(items)}
            for status in ("planned", "running", "submitted", "failed", "stale"):
                item_progress[status] = sum(1 for i in items if i["status"] == status)
            item_progress["reuse_bound"] = len(bound_items & {i["id"] for i in items})
            usable = ResearchService(self.context).usable_basis(batch_id)
            drift_by_binding = {d["binding_id"] for d in self.reuse_drift(batch_id)}
            bound_rows = conn.execute(
                """SELECT id FROM research_reuse_bindings
                   WHERE target_batch_id=? AND status='active'""", (batch_id,)).fetchall()
            reuse_covered = sum(1 for r in bound_rows if r["id"] not in drift_by_binding)
            adoption = {"pending": 0, "adopted": 0, "rejected": 0}
            for row in usable["items"]:
                state = row.get("interpretation_human_adoption_status") or \
                    row.get("source_human_adoption_status") or "pending"
                adoption[state] = adoption.get(state, 0) + 1
            layer_completion = {
                "source_records_stable": sum(
                    1 for r in usable["items"] if r.get("source_content_state") == "stable"),
                "interpretations_stable": sum(
                    1 for r in usable["items"] if r.get("interpretation_content_state") == "stable"),
            }
        return {"batch_id": batch_id, "item_progress": item_progress,
                "work_usable_coverage": {"usable": usable["usable_count"],
                                         "total": usable["total"],
                                         "reuse_covered_items": reuse_covered,
                                         "note": "usable=本批自身记录的可用口径；"
                                                 "reuse 项的 work 覆盖以有效绑定且无漂移计，"
                                                 "两个口径分列不得相加冒充本批生产"},
                "layer_completion": layer_completion,
                "human_adoption": adoption,
                "reuse_drift": self.reuse_drift(batch_id),
                "reporting_rule": "item 进度、work 可用覆盖、层完成与人工采纳分列；"
                                  "reuse_bound 只表示调度闭环，不冒充本批生产"}

    # ----- citation graph -----
    def add_reference(self, *, citing_work_id: str | None, external_object: dict,
                      match_status: str = "candidate", note: str = "") -> dict:
        if not isinstance(external_object, dict) or not external_object.get("title"):
            raise invalid_payload("external_object requires at least a title")
        if match_status not in MATCH_STATUSES:
            raise invalid_payload(f"match_status must be one of {MATCH_STATUSES}")
        if match_status == "matched":
            raise invalid_payload("use match_reference to bind a verified internal identity")
        reference_id, now = _id("RREF"), _now()
        with closing(self._write_conn()) as conn:
            conn.execute(
                """INSERT INTO research_reference_objects
                (id,citing_work_id,external_object_json,match_status,matched_work_id,
                 match_evidence_json,created_at,updated_at) VALUES (?,?,?,?,NULL,NULL,?,?)""",
                (reference_id, citing_work_id,
                 json.dumps(external_object, ensure_ascii=False), match_status, now, now),
            )
            conn.commit()
        return {"reference_id": reference_id, "match_status": match_status}

    def _identity_basis_check(self, conn: sqlite3.Connection, work_id: str,
                              evidence: dict) -> dict:
        """PLATFORM-005: match on catalog work identity, never title similarity.

        The evidence must carry an ``identity_basis`` with a verifiable key —
        DOI, arXiv, or the full (title, authors, year) triple — that EQUALS the
        catalog work's identity.  A mere title resemblance is rejected: the
        o3-mini card must not match the combined o3/o4-mini card.
        """
        basis = evidence.get("identity_basis")
        if not isinstance(basis, dict) or not basis:
            raise invalid_payload(
                "match evidence requires an identity_basis object with doi, arxiv, "
                "or the full title+authors+year triple; title similarity alone "
                "is not an identity claim")
        catalog = catalog_work_identity(self.context, work_id)
        if catalog is None:
            raise invalid_payload(
                f"work {work_id} has no catalog identity row to verify against; "
                "identity-based matching fails closed when the catalog is unavailable")
        verified: list[str] = []
        doi_basis = clean_identifier(basis.get("doi"), kind="doi")
        work_doi = clean_identifier(catalog.get("doi"), kind="doi")
        if doi_basis is not None and doi_basis == work_doi:
            verified.append("doi")
        arxiv_basis = clean_identifier(basis.get("arxiv"), kind="arxiv")
        work_arxiv = clean_identifier(catalog.get("arxiv_id"), kind="arxiv")
        if arxiv_basis is not None and arxiv_basis == work_arxiv:
            verified.append("arxiv")
        title = str(basis.get("title") or "").strip()
        authors = {str(a).strip().casefold() for a in (basis.get("authors") or []) if a}
        work_title = str(catalog.get("title") or "").strip()
        work_authors = {str(a).strip().casefold() for a in catalog.get("authors") or []}
        if title and work_title and authors and work_authors:
            try:
                year_ok = (basis.get("year") is not None
                           and int(basis.get("year")) == int(catalog.get("year") or 0))
            except (TypeError, ValueError):
                year_ok = False
            if (title.casefold() == work_title.casefold()
                    and (authors & work_authors) and year_ok):
                verified.append("title_full_triple")
        if not verified:
            raise invalid_payload(
                "identity_basis does not verify against the catalog work "
                f"{work_id} (title={catalog.get('title')!r}); matching by title "
                "similarity is rejected — disambiguate first (e.g. o3-mini vs "
                "o3/o4-mini combined cards are different works)")
        return {"verified_keys": verified, "catalog_title": work_title}

    def match_reference(self, reference_id: str, *, work_id: str,
                        evidence: dict, note: str = "") -> dict:
        """Bind a reference object to an internal work with verifiable evidence (A1).

        PLATFORM-005: the match TARGET is validated against the catalog work
        identity — the referenced work does NOT need a research source or its
        own batch.  The anchor must still live in a snapshot of the *citing*
        work (where the reference string was seen); identity match and cite
        verification stay separate.  There is deliberately no fallback that
        invents a citing side.
        """
        anchor = self._validated_anchor(evidence)
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_reference_objects WHERE id=?", (reference_id,)
            ).fetchone()
            if not row:
                raise not_found_error(reference_id)
            if row["lifecycle_status"] != "active":
                raise invalid_payload(
                    f"reference is {row['lifecycle_status']}; retired/merged objects "
                    "cannot be matched")
            citing = row["citing_work_id"]
            if not citing:
                raise invalid_payload(
                    "reference must declare its citing work before a match can be evidenced")
            if not work_exists(self.context, work_id):
                raise not_found_error(f"work not found in catalog or research library: {work_id}")
            identity = self._identity_basis_check(conn, work_id, evidence)
            self._anchor_belongs_to_work(conn, anchor, citing,
                                         "match evidence must come from the citing work's snapshot")
            now = _now()
            previous_work = row["matched_work_id"]
            previously_matched = row["match_status"] == "matched" and previous_work
            # B3: a (re)match is a new identity claim.  The old verification was
            # performed against the previous identity/evidence, so it is stale
            # the moment this match commits — never carried over.
            conn.execute(
                "UPDATE research_cites SET verified=0 WHERE reference_object_id=?",
                (reference_id,),
            )
            match_evidence = {
                **anchor, "note": note, "identity_basis_result": identity,
                "matched_at": now,
                "previous": ({"matched_work_id": previous_work,
                              "verification_revoked": True} if previously_matched else None),
            }
            conn.execute(
                """UPDATE research_reference_objects SET match_status='matched',matched_work_id=?,
                   match_evidence_json=?,updated_at=? WHERE id=?""",
                (work_id, json.dumps(match_evidence, ensure_ascii=False), now, reference_id),
            )
            conn.execute(
                """INSERT OR IGNORE INTO research_cites
                (id,citing_work_id,reference_object_id,evidence_json,verified,created_at)
                VALUES (?,?,?,?,0,?)""",
                (_id("RCIT"), citing, reference_id, json.dumps(anchor, ensure_ascii=False), now),
            )
            conn.commit()
        return {"reference_id": reference_id, "match_status": "matched",
                "matched_work_id": work_id,
                "previous_matched_work_id": previous_work,
                "verification_revoked": bool(previously_matched),
                "identity_basis_result": identity}

    def update_reference_status(self, reference_id: str, *, match_status: str,
                                note: str = "") -> dict:
        if match_status not in {"candidate", "unmatched", "ambiguous"}:
            raise invalid_payload("status must be candidate, unmatched or ambiguous")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_reference_objects WHERE id=?", (reference_id,)
            ).fetchone()
            if not row:
                raise not_found_error(reference_id)
            if row["lifecycle_status"] != "active":
                raise invalid_payload(
                    f"reference is {row['lifecycle_status']}; lifecycle governance "
                    "(correct/merge/retire) applies first")
            now = _now()
            if row["match_status"] == "matched" and match_status != "matched":
                # leaving matched revokes the identity and its verified edges (A1)
                conn.execute(
                    "UPDATE research_cites SET verified=0 WHERE reference_object_id=?",
                    (reference_id,),
                )
            conn.execute(
                """UPDATE research_reference_objects SET match_status=?,matched_work_id=NULL,
                   match_evidence_json=?,updated_at=? WHERE id=?""",
                (match_status,
                 json.dumps({"note": note, "revoked_at": now}, ensure_ascii=False) if note
                 else None,
                 now, reference_id),
            )
            conn.commit()
        return {"reference_id": reference_id, "match_status": match_status,
                "cites_revoked": row["match_status"] == "matched"}

    def verify_cite(self, citing_work_id: str, reference_id: str, *, evidence: dict) -> dict:
        """Mark a cites edge verified — only when the reference identity is
        matched and the verification quote really occurs in the *citing*
        work's text (A1: 核验证据来自被引论文快照的假核验不成立)."""
        anchor = self._validated_anchor(evidence)
        with closing(self._write_conn()) as conn:
            reference = conn.execute(
                "SELECT * FROM research_reference_objects WHERE id=?", (reference_id,)
            ).fetchone()
            if not reference:
                raise not_found_error(reference_id)
            if reference["match_status"] != "matched" or not reference["matched_work_id"]:
                raise invalid_payload(
                    "cannot verify a citation whose reference is not matched to an internal work")
            if citing_work_id != reference["citing_work_id"]:
                raise invalid_payload(
                    f"reference {reference_id} was extracted from work "
                    f"{reference['citing_work_id']}, not {citing_work_id}")
            self._anchor_belongs_to_work(conn, anchor, citing_work_id,
                                         "verification evidence must come from the citing work's snapshot")
            row = conn.execute(
                "SELECT * FROM research_cites WHERE citing_work_id=? AND reference_object_id=?",
                (citing_work_id, reference_id),
            ).fetchone()
            if not row:
                raise not_found_error(f"{citing_work_id}/{reference_id}")
            conn.execute(
                "UPDATE research_cites SET verified=1,evidence_json=?,created_at=created_at WHERE id=?",
                (json.dumps(anchor, ensure_ascii=False), row["id"]),
            )
            conn.commit()
            return {"citing_work_id": citing_work_id, "reference_id": reference_id,
                    "matched_work_id": reference["matched_work_id"],
                    "verified": True}

    def _anchor_belongs_to_work(self, conn: sqlite3.Connection, anchor: dict,
                                work_id: str, message: str) -> None:
        """The evidence anchor's snapshot must belong to the given work (A1)."""
        snapshot = conn.execute(
            """SELECT t.source_id, s.work_id FROM research_text_snapshots t
               JOIN research_sources s ON s.id=t.source_id WHERE t.id=?""",
            (anchor["snapshot_id"],),
        ).fetchone()
        if not snapshot or snapshot["work_id"] != work_id:
            raise invalid_payload(
                f"{message}: snapshot {anchor['snapshot_id']} does not belong to work {work_id}")

    def _validated_anchor(self, evidence: dict) -> dict:
        """Check a text anchor against its bound immutable snapshot."""
        snapshot_id = evidence.get("snapshot_id")
        quote = str(evidence.get("quote", ""))
        if not snapshot_id or not quote:
            raise invalid_payload("evidence requires snapshot_id and quote")
        start = evidence.get("start_offset")
        with closing(self.context.connect(read_only=True)) as conn:
            snapshot = conn.execute(
                "SELECT * FROM research_text_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
        if not snapshot:
            raise not_found_error(snapshot_id)
        content = snapshot["content_text"]
        if start is None:
            start = content.find(quote)
        end = evidence.get("end_offset", start + len(quote) if start >= 0 else -1)
        if start < 0 or end != start + len(quote) or content[start:end] != quote:
            raise invalid_payload("evidence anchor does not match the bound snapshot")
        keys = snapshot.keys()
        return {"snapshot_id": snapshot_id, "quote": quote,
                "start_offset": start, "end_offset": end,
                # U19(R6): the citation path projects the SAME full snapshot
                # identity as the C/D path — correspondence offset and page
                # geometry included — so all entries validate one way.
                "locator": _validated_locator(evidence.get("locator"), {
                    "content_text": content,
                    "version": snapshot["version"],
                    "page_count": snapshot["page_count"] if "page_count" in keys else None,
                    "page_width": snapshot["page_width"] if "page_width" in keys else None,
                    "page_height": snapshot["page_height"] if "page_height" in keys else None,
                    "start_offset": start,
                })}

    # ----- PLATFORM-002: reference lifecycle (correct/merge/retire) -----

    def _reference_event(self, conn: sqlite3.Connection, *, reference_id: str,
                         action: str, actor_id: str, event_key: str, reason: str,
                         basis: dict | None = None,
                         before: dict | None = None, after: dict | None = None):
        """Append an idempotent reference event; same-key replay adds no row.

        A key that names a different reference/action fails closed instead of
        silently re-targeting the correction.
        """
        if not event_key.strip() or not reason.strip() or not actor_id.strip():
            raise invalid_payload("event_key, reason and actor_id are required")
        replay = conn.execute(
            "SELECT * FROM research_reference_events WHERE event_key=?",
            (event_key,)).fetchone()
        if replay:
            if replay["reference_id"] != reference_id or replay["action"] != action:
                raise revision_conflict(
                    f"event_key already belongs to another {replay['action']} event "
                    f"on {replay['reference_id']}; use a new key")
            return replay, True
        event_id, now = _id("RREV"), _now()
        conn.execute(
            """INSERT INTO research_reference_events
               (id,reference_id,action,actor_id,event_key,reason,basis_json,
                before_json,after_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (event_id, reference_id, action, actor_id, event_key, reason,
             json.dumps(basis, ensure_ascii=False) if basis is not None else None,
             json.dumps(before, ensure_ascii=False) if before is not None else None,
             json.dumps(after, ensure_ascii=False) if after is not None else None, now))
        return event_id, False

    def correct_reference(self, reference_id: str, *, corrections: dict,
                          reason: str, actor_id: str, event_key: str,
                          basis: dict | None = None) -> dict:
        """Correct external-object fields with full before/after audit."""
        if not isinstance(corrections, dict) or not corrections:
            raise invalid_payload("corrections must be a non-empty object")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_reference(conn, reference_id)
            if row["lifecycle_status"] != "active":
                raise invalid_payload(
                    f"reference is {row['lifecycle_status']}; correct an active object "
                    "(or its canonical target after a merge)")
            event_id, replayed = self._reference_event(
                conn, reference_id=reference_id, action="corrected",
                actor_id=actor_id, event_key=event_key, reason=reason, basis=basis)
            if replayed:
                conn.commit()
                return {"reference_id": reference_id, "replayed": True,
                        "event_id": event_id["id"] if isinstance(event_id, sqlite3.Row) else event_id}
            external = json.loads(row["external_object_json"])
            before = {key: external.get(key) for key in corrections}
            external.update(corrections)
            now = _now()
            history = json.loads(row["correction_json"] or "[]")
            history.append({"event_key": event_key, "reason": reason,
                            "actor_id": actor_id, "at": now})
            conn.execute(
                """UPDATE research_reference_objects SET external_object_json=?,
                   correction_json=?,updated_at=? WHERE id=?""",
                (json.dumps(external, ensure_ascii=False),
                 json.dumps(history, ensure_ascii=False), now, reference_id))
            conn.commit()
        return {"reference_id": reference_id, "event_id": event_id,
                "corrected_fields": sorted(corrections), "before": before,
                "after": corrections, "replayed": False,
                "match_status": row["match_status"], "lifecycle_status": "active"}

    def merge_references(self, reference_id: str, *, canonical_reference_id: str,
                         reason: str, actor_id: str, event_key: str,
                         basis: dict | None = None) -> dict:
        """Merge a duplicate into its canonical object — no physical delete.

        The duplicate keeps its full history (lifecycle=merged, canonical
        pointer).  Its verified cites edges are revoked rather than silently
        surviving: re-verification must happen against the canonical object's
        own edges.  Nothing is merged automatically by title similarity — the
        canonical target is an explicit decision with a reason.
        """
        if reference_id == canonical_reference_id:
            raise invalid_payload("cannot merge a reference into itself")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_reference(conn, reference_id)
            event_id, replayed = self._reference_event(
                conn, reference_id=reference_id, action="merged",
                actor_id=actor_id, event_key=event_key, reason=reason, basis=basis)
            if replayed:
                conn.commit()
                return {"reference_id": reference_id, "replayed": True,
                        "event_id": event_id["id"] if isinstance(event_id, sqlite3.Row) else event_id}
            canonical = self._require_reference(conn, canonical_reference_id)
            if row["lifecycle_status"] != "active":
                raise invalid_payload(
                    f"reference is already {row['lifecycle_status']}")
            if canonical["lifecycle_status"] != "active":
                raise invalid_payload(
                    f"canonical target is {canonical['lifecycle_status']}; "
                    "merge into an active object")
            revoked = conn.execute(
                "SELECT COUNT(*) FROM research_cites WHERE reference_object_id=? AND verified=1",
                (reference_id,)).fetchone()[0]
            conn.execute(
                "UPDATE research_cites SET verified=0 WHERE reference_object_id=?",
                (reference_id,))
            now = _now()
            history = json.loads(row["correction_json"] or "[]")
            history.append({"event_key": event_key, "action": "merged",
                            "canonical_reference_id": canonical_reference_id,
                            "reason": reason, "actor_id": actor_id, "at": now})
            conn.execute(
                """UPDATE research_reference_objects SET lifecycle_status='merged',
                   canonical_reference_id=?,correction_json=?,updated_at=?
                   WHERE id=?""",
                (canonical_reference_id, json.dumps(history, ensure_ascii=False),
                 now, reference_id))
            conn.commit()
        return {"reference_id": reference_id,
                "canonical_reference_id": canonical_reference_id,
                "event_id": event_id, "cites_verification_revoked": revoked,
                "match_status": row["match_status"], "replayed": False,
                "edge_semantics": "重复项的 cites 边核验已撤销；如需核验请对 canonical "
                                  "对象自身的边重新执行 verify，不自动迁移边"}

    def retire_reference(self, reference_id: str, *, reason: str, actor_id: str,
                         event_key: str, basis: dict | None = None) -> dict:
        """Retire a dirty/placeholder reference — distinct from unmatched.

        Retired objects leave the active candidate set and listings but stay
        fully queryable with history; verified edges are revoked so a retired
        identity cannot keep lending verification to a cites edge.
        """
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._require_reference(conn, reference_id)
            event_id, replayed = self._reference_event(
                conn, reference_id=reference_id, action="retired",
                actor_id=actor_id, event_key=event_key, reason=reason, basis=basis)
            if replayed:
                conn.commit()
                return {"reference_id": reference_id, "replayed": True,
                        "event_id": event_id["id"] if isinstance(event_id, sqlite3.Row) else event_id}
            if row["lifecycle_status"] != "active":
                raise invalid_payload(f"reference is already {row['lifecycle_status']}")
            revoked = conn.execute(
                "SELECT COUNT(*) FROM research_cites WHERE reference_object_id=? AND verified=1",
                (reference_id,)).fetchone()[0]
            conn.execute(
                "UPDATE research_cites SET verified=0 WHERE reference_object_id=?",
                (reference_id,))
            now = _now()
            history = json.loads(row["correction_json"] or "[]")
            history.append({"event_key": event_key, "action": "retired",
                            "reason": reason, "actor_id": actor_id, "at": now})
            conn.execute(
                """UPDATE research_reference_objects SET lifecycle_status='retired',
                   correction_json=?,updated_at=? WHERE id=?""",
                (json.dumps(history, ensure_ascii=False), now, reference_id))
            conn.commit()
        return {"reference_id": reference_id, "event_id": event_id,
                "cites_verification_revoked": revoked,
                "match_status": row["match_status"], "lifecycle_status": "retired",
                "replayed": False,
                "note": "retired ≠ unmatched：unmatched 是真实外部文献未匹配；"
                        "retired 是本库对象的治理决定，历史保留可回查"}

    def _require_reference(self, conn: sqlite3.Connection, reference_id: str):
        row = conn.execute(
            "SELECT * FROM research_reference_objects WHERE id=?", (reference_id,)).fetchone()
        if not row:
            raise not_found_error(reference_id)
        return row

    def reference_history(self, reference_id: str) -> dict:
        with closing(self.context.connect(read_only=True)) as conn:
            row = self._require_reference(conn, reference_id)
            events = [dict(r) for r in conn.execute(
                """SELECT * FROM research_reference_events WHERE reference_id=?
                   ORDER BY created_at""", (reference_id,))]
        return {"reference_id": reference_id,
                "lifecycle_status": row["lifecycle_status"],
                "canonical_reference_id": row["canonical_reference_id"],
                "correction_history": json.loads(row["correction_json"] or "null"),
                "events": events}

    def citations_view(self, work_id: str | None = None,
                       lifecycle: str = "active") -> dict:
        with closing(self.context.connect(read_only=True)) as conn:
            for table in ("research_reference_objects", "research_cites"):
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    raise dependency_unavailable(
                        "citation graph tables are not initialized in this research store; "
                        "run the v5 schema migration first")
            if lifecycle not in ("active", "retired", "merged", "all"):
                raise invalid_payload(
                    "lifecycle must be active, retired, merged or all")
            where, params = [], []
            if work_id:
                where.append("r.citing_work_id=?")
                params.append(work_id)
            if lifecycle != "all":
                where.append("r.lifecycle_status=?")
                params.append(lifecycle)
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            references = [dict(r) for r in conn.execute(
                "SELECT * FROM research_reference_objects r" + clause + " ORDER BY r.created_at", params
            )]
            for item in references:
                item["external_object"] = json.loads(item.pop("external_object_json"))
                item["match_evidence"] = json.loads(item.pop("match_evidence_json") or "null")
            edges = [dict(r) for r in conn.execute(
                """SELECT c.* FROM research_cites c JOIN research_reference_objects r
                   ON r.id=c.reference_object_id""" + clause + " ORDER BY c.created_at", params
            )]
            for edge in edges:
                edge["evidence"] = json.loads(edge.pop("evidence_json"))
                edge["verified"] = bool(edge["verified"])
            summary_where, summary_params = (" WHERE r.citing_work_id=?", [work_id]) if work_id else ("", [])
            stats = {"by_match_status": {r[0]: r[1] for r in conn.execute(
                         f"""SELECT match_status, COUNT(*) FROM research_reference_objects r
                             {summary_where} GROUP BY match_status""", summary_params)},
                     "by_lifecycle": {r[0]: r[1] for r in conn.execute(
                         f"""SELECT lifecycle_status, COUNT(*) FROM research_reference_objects r
                             {summary_where} GROUP BY lifecycle_status""", summary_params)}}
            return {"work_id": work_id, "lifecycle": lifecycle,
                    "references": references, "cites": edges, "stats": stats,
                    "contract_rule": "cites 边需有核验证据；未匹配身份保留为候选/未匹配，不静默绑定；"
                                     "retired/merged 保留历史，默认列表只显示 active"}

    # ----- task packages -----
    def environment_id(self) -> str:
        seed = f"{self.context.library_root.resolve()}|{self.context.db_path.resolve()}|{CONTRACT['version']}"
        return "ENV-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    def create_task_package(self, batch_id: str, *, worker_owner: str,
                            lease_seconds: int = 900, note: str = "") -> dict:
        definition_service = DefinitionService(self.context)
        with closing(self.context.connect(read_only=True)) as conn:
            batch = conn.execute("SELECT * FROM research_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                raise not_found_error(batch_id)
            # B5: the package consumes the batch's PINNED release, so
            # re-fetching a task package cannot drift to a newer bundle.
            pinned = batch["release_id"] if "release_id" in batch.keys() else None
            release = definition_service.resolve_release(pinned) if pinned                 else definition_service.resolve_release(None)
            v5 = research_v5_available(conn)
            items = conn.execute(
                f"""SELECT bi.id AS item_id, bi.status, bi.attempt, bi.source_id, bi.snapshot_id,
                       s.work_id, s.citation_key, t.content_sha256 AS snapshot_sha256,
                       r.id AS source_record_id, r.version AS source_record_version,
                       {_c(v5, "r.content_state")} AS source_record_content_state,
                       i.id AS interpretation_id, i.version AS interpretation_version,
                       {_c(v5, "i.content_state")} AS interpretation_content_state
                FROM research_batch_items bi
                JOIN research_sources s ON s.id=bi.source_id
                JOIN research_text_snapshots t ON t.id=bi.snapshot_id
                LEFT JOIN research_source_records r ON r.id=bi.source_record_id
                LEFT JOIN research_interpretations i ON i.id=bi.interpretation_id
                WHERE bi.batch_id=? ORDER BY bi.id""", (batch_id,)
            ).fetchall()
            targets = None
            if batch["plan_targets_json"]:
                try:
                    targets = json.loads(batch["plan_targets_json"])
                except (TypeError, ValueError):
                    targets = None
            from .research_service import _interpretation_not_required
            # B7: the package carries the selected effective baseline per item so
            # a worker never mistakes the current pointer (possibly a pending
            # candidate) for the approved baseline.
            from .research_service import ResearchService
            baseline_by_source = {
                b["source_id"]: {"source_record_id": b["source_record_id"],
                                 "interpretation_id": b["interpretation_id"],
                                 "usable": b["usable"]}
                for b in ResearchService(self.context).usable_basis(batch_id)["items"]}
            item_dicts = []
            for row in items:
                item = dict(row)
                # B6: the package states the per-source completion contract —
                # which layers the task actually owes, so C-only scopes can
                # finish independently and D-not-applicable is not forced.
                item["interpretation_required"] = not _interpretation_not_required(
                    conn, batch_id, item["source_id"], (
                        conn.execute("SELECT payload_json FROM research_source_records WHERE id=?",
                                     (item["source_record_id"],)).fetchone()
                        if item["source_record_id"] else None))
                item["selected_baseline"] = baseline_by_source.get(item["source_id"])
                item_dicts.append(item)
        package = {
            "package": "research-task-package",
            "contract": CONTRACT["contract"],
            "contract_version": int(CONTRACT["version"]),
            "environment_id": self.environment_id(),
            "issued_at": _now(),
            "worker_owner": worker_owner,
            "lease_seconds": lease_seconds,
            "note": note,
            "release_bundle": release,
            # B5: the package carries the FULL released composition — concepts
            # and controlled values the bound release fixes — so a worker
            # consumes definitions from the task package itself, not from a
            # locally cached draft or code constant of unknown currency.
            "released_composition": definition_service.released_composition(release["id"]),
            "batch": {"id": batch["id"], "request_key": batch["request_key"],
                      "name": batch["name"], "status": batch["status"],
                      "plan_digest": batch["plan_digest"],
                      "ontology_version": batch["ontology_version"],
                      "targets": targets},
            "items": item_dicts,
            "protocol": {
                "submission": "POST /api/research/source-records then POST /api/research/interpretations",
                "fencing": "worker_owner + attempt while lease unexpired; heartbeat to renew",
                "receipts": "pass operation_id for idempotent retries",
                "expected_head_id": "pin the head you saw; mismatch returns error=revision_conflict",
                "error_categories": list(CONTRACT["error_categories"]),
            },
        }
        with closing(self._write_conn()) as conn:
            conn.execute("UPDATE research_batches SET environment_id=?,updated_at=? WHERE id=?",
                         (package["environment_id"], _now(), batch_id))
            conn.commit()
        return package

    def verify_environment(self, environment_id: str) -> bool:
        return environment_id == self.environment_id()

    # ----- cross-paper exports -----
    def interpretation_matrix(self, batch_id: str, *, scope: str = "usable") -> dict:
        """Rows follow the SELECTED EFFECTIVE BASELINE, not the batch-item pointer.

        Contract v5 B7: the batch item may point at a pending candidate while
        the approved stable baseline stays consumable.  The usable scope must
        therefore emit the baseline rows (resolved exactly like usable_basis),
        plus C-only baselines when the task scope marks D not required.  The
        batch-item pointer rows appear in scope=all as ``current_candidate``.
        """
        if scope not in {"usable", "all"}:
            raise invalid_payload("scope must be usable or all")
        basis_rows = self.usable_basis_rows(batch_id)
        basis_by_interpretation = {
            item["interpretation_id"]: item for item in basis_rows
            if item["usable"] and item["interpretation_id"]
        }
        baseline_int_ids = sorted({item["interpretation_id"] for item in basis_rows
                                   if item["usable"] and item["interpretation_id"]})
        c_only_sources = {item["source_id"]: item["source_record_id"] for item in basis_rows
                          if item["usable"] and not item["interpretation_id"]
                          and not item["interpretation_required"]}
        with closing(self.context.connect(read_only=True)) as conn:
            if not conn.execute("SELECT 1 FROM research_batches WHERE id=?", (batch_id,)).fetchone():
                raise not_found_error(batch_id)
            v5 = research_v5_available(conn)
            pointer_ids = sorted({r["interpretation_id"] for r in conn.execute(
                "SELECT interpretation_id FROM research_batch_items "
                "WHERE batch_id=? AND interpretation_id IS NOT NULL", (batch_id,))})
            fetch_ids = sorted(set(baseline_int_ids) |
                               (set(pointer_ids) if scope == "all" else set()))
            matrix: list[dict] = []
            if fetch_ids:
                marks = ",".join("?" for _ in fetch_ids)
                rows = conn.execute(
                    f"""SELECT s.work_id, s.id AS source_id, s.citation_key,
                           i.id AS interpretation_id, i.source_record_id,
                           i.version, i.ontology_version,
                           i.ontology_keys_json, i.payload_json,
                           {_c(v5, "i.content_state")} AS content_state,
                           i.validity_status, i.agent_review_status, i.human_adoption_status,
                           {_c(v5, "i.human_adoption_scope_json")} AS human_adoption_scope_json,
                           {_c(v5, "i.source_metadata_record_id")} AS source_metadata_record_id,
                           i.snapshot_id, i.snapshot_sha256,
                           {_c(v5, "i.release_id")} AS release_id,
                           {_c(v5, "i.definition_refs_json")} AS definition_refs_json
                    FROM research_interpretations i
                    JOIN research_sources s ON s.id=i.source_id
                    WHERE i.id IN ({marks}) ORDER BY s.work_id, i.id""", fetch_ids
                ).fetchall()
                for row in rows:
                    item = dict(row)
                    item["record_layer"] = "interpretation"
                    item["basis_role"] = ("baseline"
                                          if item["interpretation_id"] in set(baseline_int_ids)
                                          else "current_candidate")
                    item["in_usable_basis"] = item["basis_role"] == "baseline"
                    item["ontology_keys"] = json.loads(item.pop("ontology_keys_json") or "[]")
                    payload = json.loads(item.pop("payload_json"))
                    # lossless payload plus the projections consumers rely on (A8)
                    item["payload"] = payload
                    item["mapping_status"] = payload.get("mapping_status")
                    item["update_object"] = payload.get("update_object")
                    item["research_role"] = payload.get("research_role")
                    item["deployment_condition"] = payload.get("deployment_condition")
                    item["associations"] = payload.get("associations") or []
                    item["positions"] = (payload.get("associations") or [{}])[0].get("positions") \
                        if payload.get("associations") else None
                    item["statement"] = payload.get("statement")
                    item["unresolved"] = payload.get("unresolved") or []
                    item["extensions"] = payload.get("extensions") or []
                    item["scope"] = payload.get("scope")
                    item["support_boundary"] = payload.get("support_boundary")
                    item["definition_refs"] = json.loads(item.pop("definition_refs_json") or "[]")
                    # B7/U24: a D row carries the actual A/C layers it was built
                    # on — the bound source record with its named extensions and
                    # units, plus the pinned metadata version — so an
                    # interpretation row is never mistaken for the whole
                    # three-layer content.
                    sr_row = conn.execute(
                        "SELECT * FROM research_source_records WHERE id=?",
                        (item["source_record_id"],)).fetchone()
                    def _evidence_rows(layer: str, record_id: str) -> list[dict]:
                        has_claims = conn.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_claims'"
                        ).fetchone() is not None
                        if not has_claims:
                            return []
                        rows = []
                        if not conn.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_evidence'"
                        ).fetchone():
                            return []
                        for ev in conn.execute(
                            """SELECT c.claim_key, c.claim_text, e.snapshot_id, e.quote,
                               e.start_offset, e.end_offset, e.locator_json
                               FROM research_claims c JOIN research_evidence e ON e.claim_id=c.id
                               WHERE c.record_layer=? AND c.record_id=?
                               ORDER BY c.claim_key, e.start_offset""", (layer, record_id)):
                            row_ev = dict(ev)
                            row_ev["locator"] = json.loads(row_ev.pop("locator_json") or "null")
                            rows.append(row_ev)
                        return rows

                    if sr_row:
                        sr = dict(sr_row)
                        sr_payload = json.loads(sr["payload_json"])
                        unit_state = _c(v5, "content_state")
                        units = []
                        has_units_table = conn.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_units'"
                        ).fetchone() is not None
                        for u in (conn.execute(
                            f"""SELECT id, unit_key, version, supersedes_id, payload_json,
                               shared_items_json, gaps_json, extensions_json,
                               agent_review_status, human_adoption_status,
                               {_c(v5, "human_adoption_scope_json")} AS human_adoption_scope_json,
                               validity_status,
                               {unit_state} AS content_state
                               FROM research_units WHERE source_record_id=?
                               AND validity_status='active' ORDER BY unit_key, version""",
                            (item["source_record_id"],)) if has_units_table else []):
                            unit = dict(u)
                            unit["payload"] = json.loads(unit.pop("payload_json"))
                            unit["shared_items"] = json.loads(unit.pop("shared_items_json") or "[]")
                            unit["gaps"] = json.loads(unit.pop("gaps_json") or "[]")
                            unit["extensions"] = json.loads(unit.pop("extensions_json") or "[]")
                            if "human_adoption_scope_json" in unit.keys():
                                unit["human_adoption_scope"] = json.loads(
                                    unit.pop("human_adoption_scope_json") or "null")
                            units.append(unit)
                        item["source_record"] = {
                            "id": sr["id"], "version": sr["version"],
                            "schema_version": sr.get("schema_version"),
                            "content_state": sr.get("content_state"),
                            "validity_status": sr["validity_status"],
                            "human_adoption_status": sr.get("human_adoption_status"),
                            "human_adoption_scope": json.loads(
                                sr["human_adoption_scope_json"] or "null")
                            if sr.get("human_adoption_scope_json") else None,
                            # B7: the actual A-layer content travels with the row —
                            # full payload, record-level shared context and the
                            # per-claim evidence that anchors it.
                            "payload": sr_payload,
                            "extensions": sr_payload.get("extensions") or [],
                            "shared_items": sr_payload.get("shared_items") or [],
                            "gaps": sr_payload.get("gaps") or [],
                            "units": units,
                            "evidence": _evidence_rows("source_record", sr["id"]),
                        }
                        item["source_record_extensions"] = sr_payload.get("extensions") or []
                    else:
                        item["source_record"] = None
                        item["source_record_extensions"] = []
                    # B7/U24: the D row's own per-claim evidence and its pinned
                    # metadata dependency (with bound resource conditions and
                    # the dependency's CURRENT review state).
                    item["evidence"] = _evidence_rows(
                        "interpretation", item["interpretation_id"]) \
                        if item.get("interpretation_id") else []
                    pinned_meta = item.pop("source_metadata_record_id", None)
                    if pinned_meta:
                        meta_row = conn.execute(
                            "SELECT id, version, payload_json, content_state, validity_status, "
                            "agent_review_status FROM research_metadata_records WHERE id=?",
                            (pinned_meta,)).fetchone()
                        if meta_row:
                            meta = dict(meta_row)
                            meta_payload = json.loads(meta.pop("payload_json"))
                            item["metadata_binding"] = {
                                "id": meta["id"], "version": meta["version"],
                                "content_state": meta["content_state"],
                                "validity_status": meta["validity_status"],
                                "agent_review_status": meta["agent_review_status"],
                                # B7(R6): the bound A layer travels COMPLETE —
                                # payload (authors etc.), named extensions and
                                # resource conditions — not only IDs/status.
                                "payload": meta_payload,
                                "authors": meta_payload.get("authors") or [],
                                "extensions": meta_payload.get("extensions") or [],
                                "resources": meta_payload.get("resources") or [],
                                "resource_observations": meta_payload.get("resource_observations") or [],
                                "review_pending": meta["agent_review_status"] != "approved"
                                or meta["content_state"] != "stable",
                            }
                        else:
                            item["metadata_binding"] = {
                                "id": pinned_meta, "version": None,
                                "note": "pinned metadata record no longer resolvable"}
                    else:
                        item["metadata_binding"] = None
                    has_source_impacts = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='research_source_impacts'").fetchone() is not None
                    impact_rows = conn.execute(
                        """SELECT new_source_record_id,impacted_unit_keys_json,
                                  change_kind,requires_rereview
                           FROM research_source_impacts WHERE interpretation_id=?
                           ORDER BY created_at""", (item["interpretation_id"],)).fetchall() \
                        if has_source_impacts else []
                    item["source_dependency_impacts"] = [
                        {"source_record_id": impact["new_source_record_id"],
                         "impacted_unit_keys": json.loads(
                             impact["impacted_unit_keys_json"] or "[]"),
                         "change_kind": impact["change_kind"],
                         "requires_rereview": bool(impact["requires_rereview"])}
                        for impact in impact_rows]
                    basis = basis_by_interpretation.get(item["interpretation_id"])
                    item["consumption_source_record_id"] = (
                        basis.get("source_record_id") if basis else item["source_record_id"])
                    item["source_dependency_review_pending"] = (
                        list(basis.get("source_dependency_review_pending") or [])
                        if basis else [])
                    if item.get("human_adoption_scope_json"):
                        item["human_adoption_scope"] = json.loads(
                            item.pop("human_adoption_scope_json"))
                    else:
                        item.pop("human_adoption_scope_json", None)
                        item["human_adoption_scope"] = None
                    claims = conn.execute(
                        "SELECT COUNT(*) FROM research_claims WHERE record_layer='interpretation' AND record_id=?",
                        (item["interpretation_id"],)).fetchone()[0]                         if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                        "AND name='research_claims'").fetchone() else 0
                    evidence = conn.execute(
                        """SELECT COUNT(*) FROM research_evidence e
                           JOIN research_claims c ON c.id=e.claim_id
                           WHERE c.record_layer='interpretation' AND c.record_id=?""",
                        (item["interpretation_id"],)).fetchone()[0]                         if claims else 0
                    item["evidence_coverage"] = {"claims": claims, "evidence_anchors": evidence}
                    matrix.append(item)
            # C-only usable baselines: consumable without an interpretation when
            # the task scope says D is not required (B6) — exported explicitly.
            for source_id, source_record_id in sorted(c_only_sources.items()):
                row = conn.execute(
                    f"""SELECT s.work_id, s.id AS source_id, s.citation_key,
                           r.id AS source_record_id, r.version AS source_record_version,
                           r.payload_json, {_c(v5, "r.schema_version")} AS ontology_version,
                           {_c(v5, "r.content_state")} AS content_state,
                           r.validity_status, r.agent_review_status, r.human_adoption_status,
                           r.human_adoption_scope_json,
                           r.snapshot_id, r.snapshot_sha256,
                           {_c(v5, "r.release_id")} AS release_id,
                           {_c(v5, "r.definition_refs_json")} AS definition_refs_json
                    FROM research_source_records r JOIN research_sources s ON s.id=r.source_id
                    WHERE r.id=?""", (source_record_id,)).fetchone()
                if not row:
                    continue
                item = dict(row)
                item["record_layer"] = "source_record"
                item["basis_role"] = "baseline"
                item["in_usable_basis"] = True
                item["interpretation_id"] = None
                item["interpretation_required"] = False
                item["version"] = item.pop("source_record_version")
                item["ontology_keys"] = []
                payload = json.loads(item.pop("payload_json"))
                item["payload"] = payload
                for key in ("mapping_status", "update_object", "research_role",
                            "deployment_condition", "statement"):
                    item[key] = None
                item["associations"] = []
                item["positions"] = None
                item["unresolved"] = []
                item["extensions"] = payload.get("extensions") or []
                item["source_record"] = None
                item["source_record_extensions"] = []
                item["metadata_binding"] = None
                if item.get("human_adoption_scope_json"):
                    item["human_adoption_scope"] = json.loads(item.pop("human_adoption_scope_json"))
                else:
                    item.pop("human_adoption_scope_json", None)
                    item["human_adoption_scope"] = None
                item["definition_refs"] = json.loads(item.pop("definition_refs_json") or "[]")
                claims = conn.execute(
                    "SELECT COUNT(*) FROM research_claims WHERE record_layer='source_record' AND record_id=?",
                    (source_record_id,)).fetchone()[0]                 if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                "AND name='research_claims'").fetchone() else 0
                evidence = conn.execute(
                    """SELECT COUNT(*) FROM research_evidence e
                       JOIN research_claims c ON c.id=e.claim_id
                       WHERE c.record_layer='source_record' AND c.record_id=?""",
                    (source_record_id,)).fetchone()[0]
                item["evidence_coverage"] = {"claims": claims, "evidence_anchors": evidence}
                matrix.append(item)
            matrix.sort(key=lambda r: (r["work_id"], r["source_id"],
                                       r["interpretation_id"] or ""))
            input_manifest = {
                "batch_id": batch_id, "scope": scope,
                "contract_version": int(CONTRACT["version"]),
                "rows": [{"work_id": r["work_id"], "source_id": r["source_id"],
                          "record_layer": r["record_layer"],
                          "record_id": r["interpretation_id"] or r["source_record_id"],
                          "record_version": r["version"],
                          "source_record_id": r["source_record_id"],
                          "consumption_source_record_id": r.get(
                              "consumption_source_record_id", r["source_record_id"]),
                          "source_dependency_review_pending": r.get(
                              "source_dependency_review_pending") or [],
                          "source_record_version": (r.get("source_record") or {}).get("version")
                          if r.get("source_record") else None,
                          "snapshot_id": r["snapshot_id"],
                          "snapshot_sha256": r["snapshot_sha256"],
                          "ontology_version": r["ontology_version"],
                          "release_id": r.get("release_id"),
                          "definition_refs": r.get("definition_refs") or [],
                          "basis_role": r["basis_role"],
                          # B7: the human overlay is part of the fixed inputs —
                          # a scoped adoption changes the export and MUST change
                          # the output identity, so history stays distinguishable.
                          "human_adoption_status": r.get("human_adoption_status"),
                          "human_adoption_scope": r.get("human_adoption_scope"),
                          "source_human_adoption_scope": (r.get("source_record") or {}).get(
                              "human_adoption_scope") if r.get("source_record") else None,
                          "metadata_binding": r.get("metadata_binding"),
                          "unit_states": [
                              {"unit_key": u["unit_key"], "version": u["version"],
                               "content_state": u.get("content_state"),
                               "validity_status": u.get("validity_status"),
                               "agent_review_status": u.get("agent_review_status")}
                              for u in (r.get("source_record") or {}).get("units", [])
                          ] if r.get("source_record") else [],
                          } for r in matrix],
            }
            result = {"batch_id": batch_id, "scope": scope, "rows": matrix,
                    "research_v5_available": v5,
                    "input_manifest": input_manifest,
                    "output_id": _export_output_id("interpretation_matrix", input_manifest),
                    "export_identity": {"contract_version": int(CONTRACT["version"]),
                                        "environment_id": self.environment_id(),
                                        "generated_at": _now()},
                    "separation_rule": "usable=已选有效基线（稳定且批准）；all 中批项指针若指向待审"
                                       "候选则标记 current_candidate，不冒充基线；D 不适用时 C-only"
                                       " 基线以 record_layer=source_record 导出"}
        # B7: register the exact inputs behind this output so a historical
        # output can always answer which inputs produced it.  A pre-conversion
        # (v4) store has no registry — the export degrades explicitly instead
        # of failing.
        result["previous_output_ids"] = self._register_output_quietly(
            "interpretation_matrix", batch_id, result["output_id"], input_manifest,
            output_payload=result)
        return result

    def citations_export(self, batch_id: str | None = None) -> dict:
        """Citation-graph export; ``batch_id`` restricts to that batch's works (A8)."""
        known_work_ids: set[str] = set()
        with closing(self.context.connect(read_only=True)) as conn:
            if batch_id:
                if not conn.execute("SELECT 1 FROM research_batches WHERE id=?", (batch_id,)).fetchone():
                    raise not_found_error(batch_id)
                known_work_ids = {r["work_id"] for r in conn.execute(
                    """SELECT DISTINCT s.work_id FROM research_batch_items bi
                       JOIN research_sources s ON s.id=bi.source_id WHERE bi.batch_id=?""",
                    (batch_id,))}
            else:
                known_work_ids = {r["work_id"] for r in conn.execute(
                    "SELECT DISTINCT work_id FROM research_sources")}
        view = self.citations_view(None)
        references = [r for r in view["references"]
                      if r.get("citing_work_id") in known_work_ids]
        kept_ids = {r["id"] for r in references}
        cites = [c for c in view["cites"] if c["reference_object_id"] in kept_ids]
        input_manifest = {"batch_id": batch_id,
                          "contract_version": int(CONTRACT["version"]),
                          "known_work_ids": sorted(known_work_ids),
                          "references": [{"id": r["id"], "citing_work_id": r["citing_work_id"],
                                          "match_status": r.get("match_status"),
                                          "matched_work_id": r.get("matched_work_id")}
                                         for r in references],
                          "cites": [{"reference_object_id": c["reference_object_id"],
                                     "verified": c["verified"]} for c in cites]}
        result = {"batch_id": batch_id,
                "references": references, "cites": cites,
                "known_work_ids": sorted(known_work_ids),
                "input_manifest": input_manifest,
                "output_id": _export_output_id("citations_export", input_manifest),
                "export_identity": {"contract_version": int(CONTRACT["version"]),
                                    "environment_id": self.environment_id(),
                                    "generated_at": _now()}}
        result["previous_output_ids"] = self._register_output_quietly(
            "citations_export", batch_id, result["output_id"], input_manifest,
            output_payload=result)
        return result

    def comparison(self, batch_id: str) -> dict:
        """Cross-paper candidate comparison by ontology concept (usable first)."""
        matrix = self.interpretation_matrix(batch_id, scope="all")
        by_concept: dict[str, list[dict]] = {}
        for row in matrix["rows"]:
            if row["record_layer"] != "interpretation":
                continue
            for key in row["ontology_keys"] or ["<unmapped>"]:
                by_concept.setdefault(key, []).append({
                    "work_id": row["work_id"], "interpretation_id": row["interpretation_id"],
                    "ontology_version": row["ontology_version"], "version": row["version"],
                    "release_id": row.get("release_id"),
                    "definition_refs": row.get("definition_refs") or [],
                    "snapshot_sha256": row.get("snapshot_sha256"),
                    "statement": row["statement"], "mapping_status": row["mapping_status"],
                    "associations": row.get("associations") or [],
                    "positions": row["positions"],
                    # B7 lossless: three-layer extensions, unresolved items and the
                    # full payload ride along instead of a whitelist projection.
                    "extensions": row.get("extensions") or [],
                    "unresolved": row.get("unresolved") or [],
                    "payload": row["payload"],
                    "scope": row.get("scope"),
                    "support_boundary": row.get("support_boundary"),
                    "source_record": row.get("source_record"),
                    "consumption_source_record_id": row.get(
                        "consumption_source_record_id", row.get("source_record_id")),
                    "source_dependency_impacts": row.get("source_dependency_impacts") or [],
                    "source_dependency_review_pending": row.get(
                        "source_dependency_review_pending") or [],
                    "source_record_extensions": row.get("source_record_extensions") or [],
                    "evidence": row.get("evidence") or [],
                    "metadata_binding": row.get("metadata_binding"),
                    "human_adoption_status": row.get("human_adoption_status"),
                    "human_adoption_scope": row.get("human_adoption_scope"),
                    "basis_role": row["basis_role"],
                    "in_usable_basis": row["in_usable_basis"],
                })
        comparison_id = _export_output_id("comparison", matrix["input_manifest"])
        result = {"batch_id": batch_id, "concepts": by_concept,
                "input_manifest": matrix["input_manifest"],
                "output_id": comparison_id,
                "export_identity": matrix["export_identity"],
                "note": "候选比较仅用于探索；稳定结论以 basis_role=baseline 为准；"
                        "C-only 基线不参与概念比较，见矩阵 record_layer=source_record 行"}
        result["previous_output_ids"] = self._register_output_quietly(
            "comparison", batch_id, comparison_id, matrix["input_manifest"],
            output_payload=result)
        return result

    def _register_output_quietly(self, kind: str, batch_id: str | None,
                                 output_id: str, input_manifest: dict,
                                 output_payload: dict | None = None) -> list[str] | None:
        # B7(R5): a read-only query must never fail because of bookkeeping —
        # registration is skipped without write permission, and the previous
        # output list is still answered from the registry when readable.
        if getattr(self.context, "read_only", False):
            try:
                with closing(self.context.connect(read_only=True)) as conn:
                    return [r[0] for r in conn.execute(
                        "SELECT output_id FROM research_output_registry "
                        "WHERE kind=? AND COALESCE(batch_id,'')=? AND output_id<>? "
                        "ORDER BY created_at",
                        (kind, batch_id or "", output_id))]
            except sqlite3.OperationalError:
                return None
        try:
            with closing(self._write_conn()) as registry_conn:
                previous = _register_output(registry_conn, kind, batch_id,
                                            output_id, input_manifest, output_payload)
                registry_conn.commit()
                return previous
        except (RuntimeError, PermissionError, sqlite3.OperationalError):
            return None  # v4 store / unwritable context: no output registry

    def usable_basis_rows(self, batch_id: str) -> list[dict]:
        from .research_service import ResearchService
        return ResearchService(self.context).usable_basis(batch_id)["items"]

    # ----- csv helpers -----
    @staticmethod
    def to_csv(rows: list[dict], columns: list[str]) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: json.dumps(row[column], ensure_ascii=False)
                             if isinstance(row.get(column), (dict, list)) else row.get(column, "")
                             for column in columns})
        return buffer.getvalue()
