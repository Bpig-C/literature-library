"""Schema and reversible bootstrap for the isolated research workflow."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .research_context import ResearchContext, REPO_ROOT


CONTRACT_PATH = REPO_ROOT / "contracts" / "research-workflow-v1.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
SCHEMA_VERSION = int(CONTRACT["schema_version"])


def compute_environment_id(library_root, db_path) -> str:
    """Stable identity of the isolated research environment (root + db + contract).

    Every write must carry this id (task packages publish it; submissions are
    rejected on mismatch), so a client pointed at a cloned/moved environment
    cannot silently write into the wrong data store.
    """
    import hashlib
    seed = f"{Path(library_root).resolve()}|{Path(db_path).resolve()}|{CONTRACT['version']}"
    return "ENV-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS research_schema_migrations (
  version INTEGER PRIMARY KEY, contract_version INTEGER NOT NULL,
  applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_sources (
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL,
  source_file_id TEXT NOT NULL UNIQUE,
  citation_key TEXT,
  source_path TEXT NOT NULL,
  snapshot_path TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  original_name TEXT,
  parse_run_id TEXT,
  parse_exists INTEGER NOT NULL DEFAULT 0 CHECK(parse_exists IN (0,1)),
  parse_quality TEXT NOT NULL DEFAULT 'unchecked'
    CHECK(parse_quality IN ('unchecked','passed','failed')),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_sources_work ON research_sources(work_id);
CREATE INDEX IF NOT EXISTS idx_research_sources_citation ON research_sources(citation_key);
CREATE TABLE IF NOT EXISTS research_source_citations (
  key TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES research_sources(id),
  kind TEXT NOT NULL DEFAULT 'alias', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_source_citations_source
  ON research_source_citations(source_id,kind,key);

CREATE TABLE IF NOT EXISTS research_text_snapshots (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES research_sources(id),
  version INTEGER NOT NULL,
  source_file_id TEXT NOT NULL,
  parse_run_id TEXT NOT NULL,
  content_text TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  parse_exists INTEGER NOT NULL DEFAULT 0 CHECK(parse_exists IN (0,1)),
  parse_quality TEXT NOT NULL DEFAULT 'unchecked'
    CHECK(parse_quality IN ('unchecked','passed','failed')),
  page_count INTEGER,
  page_width REAL,
  page_height REAL,
  page_sizes TEXT,
  page_offsets TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(source_id, version)
);
CREATE INDEX IF NOT EXISTS idx_research_text_snapshot_parse_run
  ON research_text_snapshots(source_id,parse_run_id);

CREATE TABLE IF NOT EXISTS research_batches (
  id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  parent_batch_id TEXT REFERENCES research_batches(id), status TEXT NOT NULL,
  ontology_version TEXT NOT NULL, plan_digest TEXT NOT NULL,
  environment_id TEXT, plan_targets_json TEXT,
  release_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_batch_items (
  id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES research_batches(id),
  source_id TEXT NOT NULL REFERENCES research_sources(id),
  snapshot_id TEXT NOT NULL REFERENCES research_text_snapshots(id),
  status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
  worker_owner TEXT, started_at TEXT, heartbeat_at TEXT, lease_expires_at TEXT,
  recovery_count INTEGER NOT NULL DEFAULT 0, last_recovery_at TEXT, last_recovery_note TEXT,
  last_error TEXT, source_record_id TEXT, interpretation_id TEXT,
  updated_at TEXT NOT NULL, UNIQUE(batch_id, source_id, snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_research_batch_items_batch ON research_batch_items(batch_id,status);
CREATE TABLE IF NOT EXISTS research_batch_item_events (
  id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES research_batch_items(id),
  action TEXT NOT NULL, submission_mode TEXT NOT NULL,
  worker_owner TEXT, attempt INTEGER, reason TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_batch_item_events_item
  ON research_batch_item_events(item_id,created_at);

CREATE TABLE IF NOT EXISTS research_source_records (
  id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES research_batches(id),
  source_id TEXT NOT NULL REFERENCES research_sources(id),
  source_file_id TEXT NOT NULL, parse_run_id TEXT NOT NULL,
  snapshot_id TEXT NOT NULL REFERENCES research_text_snapshots(id),
  snapshot_sha256 TEXT NOT NULL, schema_version TEXT NOT NULL,
  version INTEGER NOT NULL, payload_json TEXT NOT NULL,
  validation_status TEXT NOT NULL DEFAULT 'pending',
  agent_review_status TEXT NOT NULL DEFAULT 'pending',
  human_adoption_status TEXT NOT NULL DEFAULT 'pending',
  validity_status TEXT NOT NULL DEFAULT 'active',
  supersedes_id TEXT REFERENCES research_source_records(id),
  layer TEXT NOT NULL DEFAULT 'source_record',
  content_state TEXT NOT NULL DEFAULT 'needs_review'
    CHECK(content_state IN ('needs_completion','needs_review','stable')),
  release_id TEXT, definition_refs_json TEXT, scope_json TEXT, feedback_id TEXT,
  human_adoption_scope_json TEXT, submitted_by TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(batch_id,source_id,version)
);
CREATE INDEX IF NOT EXISTS idx_research_source_record_state
  ON research_source_records(batch_id,validation_status,agent_review_status,human_adoption_status,validity_status);
CREATE TABLE IF NOT EXISTS research_interpretations (
  id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES research_batches(id),
  source_record_id TEXT NOT NULL REFERENCES research_source_records(id),
  source_id TEXT NOT NULL REFERENCES research_sources(id),
  source_file_id TEXT NOT NULL, parse_run_id TEXT NOT NULL,
  snapshot_id TEXT NOT NULL REFERENCES research_text_snapshots(id),
  snapshot_sha256 TEXT NOT NULL, ontology_version TEXT NOT NULL,
  ontology_keys_json TEXT NOT NULL DEFAULT '[]', schema_version TEXT NOT NULL,
  version INTEGER NOT NULL, payload_json TEXT NOT NULL,
  validation_status TEXT NOT NULL DEFAULT 'pending',
  agent_review_status TEXT NOT NULL DEFAULT 'pending',
  human_adoption_status TEXT NOT NULL DEFAULT 'pending',
  validity_status TEXT NOT NULL DEFAULT 'active',
  supersedes_id TEXT REFERENCES research_interpretations(id),
  layer TEXT NOT NULL DEFAULT 'interpretation',
  content_state TEXT NOT NULL DEFAULT 'needs_review'
    CHECK(content_state IN ('needs_completion','needs_review','stable')),
  release_id TEXT, definition_refs_json TEXT, scope_json TEXT, feedback_id TEXT,
  human_adoption_scope_json TEXT, submitted_by TEXT,
  source_metadata_record_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(batch_id,source_record_id,version)
);
CREATE INDEX IF NOT EXISTS idx_research_interpretation_state
  ON research_interpretations(batch_id,agent_review_status,human_adoption_status,validity_status);

CREATE TABLE IF NOT EXISTS research_claims (
  id TEXT PRIMARY KEY, record_layer TEXT NOT NULL, record_id TEXT NOT NULL,
  claim_key TEXT NOT NULL, claim_text TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(record_layer,record_id,claim_key)
);
CREATE TABLE IF NOT EXISTS research_evidence (
  id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES research_claims(id),
  snapshot_id TEXT NOT NULL REFERENCES research_text_snapshots(id),
  quote TEXT NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
  locator_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_evidence_claim ON research_evidence(claim_id);

CREATE TABLE IF NOT EXISTS research_review_events (
  id TEXT PRIMARY KEY, record_layer TEXT NOT NULL, record_id TEXT NOT NULL,
  ontology_proposal_id TEXT REFERENCES research_ontology_proposals(id),
  actor_type TEXT NOT NULL, decision TEXT NOT NULL, note TEXT,
  scope_json TEXT, actor_id TEXT, record_version INTEGER,
  basis_json TEXT, event_key TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_review_record
  ON research_review_events(record_layer,record_id,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_research_review_event_key
  ON research_review_events(event_key) WHERE event_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS research_ontology_versions (
  version TEXT PRIMARY KEY, parent_version TEXT, status TEXT NOT NULL,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL, published_at TEXT
);
CREATE TABLE IF NOT EXISTS research_ontology_proposals (
  id TEXT PRIMARY KEY, base_version TEXT NOT NULL,
  proposed_version TEXT NOT NULL UNIQUE, changed_keys_json TEXT NOT NULL,
  payload_json TEXT NOT NULL, status TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_ontology_impacts (
  proposal_id TEXT NOT NULL REFERENCES research_ontology_proposals(id),
  interpretation_id TEXT NOT NULL REFERENCES research_interpretations(id),
  impacted_keys_json TEXT NOT NULL, requires_rereview INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(proposal_id, interpretation_id)
);
CREATE TABLE IF NOT EXISTS research_definitions (
  id TEXT PRIMARY KEY,
  layer TEXT NOT NULL CHECK(layer IN ('metadata','source_record','interpretation','ontology')),
  version TEXT NOT NULL, sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','released','retired')),
  parent_version TEXT, created_at TEXT NOT NULL,
  UNIQUE(layer,version)
);
CREATE TABLE IF NOT EXISTS research_definition_releases (
  id TEXT PRIMARY KEY, contract_version INTEGER NOT NULL,
  definition_refs_json TEXT NOT NULL, note TEXT, released_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_metadata_records (
  id TEXT PRIMARY KEY, batch_id TEXT, work_id TEXT NOT NULL,
  version INTEGER NOT NULL, supersedes_id TEXT,
  payload_json TEXT NOT NULL,
  content_state TEXT NOT NULL DEFAULT 'needs_review'
    CHECK(content_state IN ('needs_completion','needs_review','stable')),
  validation_status TEXT NOT NULL DEFAULT 'passed'
    CHECK(validation_status IN ('pending','passed','failed')),
  agent_review_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(agent_review_status IN ('pending','approved','needs_revision','rejected')),
  human_adoption_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(human_adoption_status IN ('pending','adopted','rejected')),
  validity_status TEXT NOT NULL DEFAULT 'active'
    CHECK(validity_status IN ('active','stale','superseded')),
  release_id TEXT, definition_refs_json TEXT, feedback_id TEXT,
  human_adoption_scope_json TEXT, submitted_by TEXT,
  propagation_state_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(work_id,version)
);
CREATE TABLE IF NOT EXISTS research_units (
  id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, work_id TEXT NOT NULL,
  source_record_id TEXT NOT NULL REFERENCES research_source_records(id),
  unit_key TEXT NOT NULL, version INTEGER NOT NULL, supersedes_id TEXT,
  payload_json TEXT NOT NULL, shared_items_json TEXT, gaps_json TEXT, extensions_json TEXT,
  content_state TEXT NOT NULL DEFAULT 'needs_review'
    CHECK(content_state IN ('needs_completion','needs_review','stable')),
  validation_status TEXT NOT NULL DEFAULT 'passed'
    CHECK(validation_status IN ('pending','passed','failed')),
  agent_review_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(agent_review_status IN ('pending','approved','needs_revision','rejected')),
  human_adoption_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(human_adoption_status IN ('pending','adopted','rejected')),
  validity_status TEXT NOT NULL DEFAULT 'active'
    CHECK(validity_status IN ('active','stale','superseded')),
  release_id TEXT, definition_refs_json TEXT,
  human_adoption_scope_json TEXT, submitted_by TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(source_record_id,unit_key,version)
);
CREATE INDEX IF NOT EXISTS idx_research_units_record ON research_units(source_record_id);
CREATE INDEX IF NOT EXISTS idx_research_units_state ON research_units(content_state);
CREATE TABLE IF NOT EXISTS research_feedback (
  id TEXT PRIMARY KEY, layer TEXT NOT NULL, target_id TEXT NOT NULL, target_version INTEGER,
  work_id TEXT, batch_id TEXT, explicit_claim TEXT NOT NULL, detail TEXT,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open','formal_revision_created','closed')),
  outcome TEXT CHECK(outcome IS NULL OR outcome IN
    ('corrected','partially_corrected','retained_with_evidence','unresolved')),
  formal_revision_id TEXT, resolution_note TEXT, resolution_evidence_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_feedback_target ON research_feedback(layer,target_id);
CREATE TABLE IF NOT EXISTS research_reference_objects (
  id TEXT PRIMARY KEY, citing_work_id TEXT,
  external_object_json TEXT NOT NULL,
  match_status TEXT NOT NULL DEFAULT 'candidate'
    CHECK(match_status IN ('candidate','matched','unmatched','ambiguous')),
  matched_work_id TEXT, match_evidence_json TEXT,
  lifecycle_status TEXT NOT NULL DEFAULT 'active'
    CHECK(lifecycle_status IN ('active','retired','merged')),
  canonical_reference_id TEXT,
  correction_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_reference_match ON research_reference_objects(match_status);
CREATE INDEX IF NOT EXISTS idx_research_reference_lifecycle
  ON research_reference_objects(lifecycle_status,canonical_reference_id);
CREATE TABLE IF NOT EXISTS research_reference_events (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES research_reference_objects(id),
  action TEXT NOT NULL CHECK(action IN ('created','matched','status_changed','corrected','merged','retired')),
  actor_id TEXT NOT NULL, event_key TEXT UNIQUE, reason TEXT NOT NULL,
  basis_json TEXT, before_json TEXT, after_json TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_reference_events_ref
  ON research_reference_events(reference_id,created_at);
CREATE TABLE IF NOT EXISTS research_cites (
  id TEXT PRIMARY KEY, citing_work_id TEXT NOT NULL,
  reference_object_id TEXT NOT NULL REFERENCES research_reference_objects(id),
  evidence_json TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(citing_work_id,reference_object_id)
);
CREATE INDEX IF NOT EXISTS idx_research_cites_citing ON research_cites(citing_work_id);
CREATE TABLE IF NOT EXISTS research_task_receipts (
  operation_id TEXT PRIMARY KEY, task_kind TEXT NOT NULL, target_id TEXT,
  batch_id TEXT, worker_owner TEXT, result_json TEXT NOT NULL,
  request_digest TEXT, environment_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_operation_effects (
  operation_id TEXT NOT NULL, seq INTEGER NOT NULL, result_json TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY(operation_id, seq)
);
CREATE TABLE IF NOT EXISTS research_output_registry (
  output_id TEXT NOT NULL, kind TEXT NOT NULL, batch_id TEXT,
  inputs_json TEXT NOT NULL, output_json TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY(output_id, kind)
);
CREATE TABLE IF NOT EXISTS research_source_impacts (
  new_source_record_id TEXT NOT NULL,
  prior_source_record_id TEXT NOT NULL,
  interpretation_id TEXT NOT NULL,
  impacted_unit_keys_json TEXT NOT NULL DEFAULT '[]',
  change_kind TEXT NOT NULL,
  requires_rereview INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  PRIMARY KEY(new_source_record_id, interpretation_id, change_kind)
);
CREATE INDEX IF NOT EXISTS idx_research_source_impacts_interpretation
  ON research_source_impacts(interpretation_id, requires_rereview);
CREATE TABLE IF NOT EXISTS research_metadata_tasks (
  id TEXT PRIMARY KEY, work_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('absent','pending','conflict','stable','excluded')),
  reason TEXT NOT NULL DEFAULT '', metadata_record_id TEXT,
  operation_id TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_metadata_tasks_status
  ON research_metadata_tasks(status,updated_at);
CREATE TABLE IF NOT EXISTS research_reuse_bindings (
  id TEXT PRIMARY KEY,
  batch_item_id TEXT NOT NULL REFERENCES research_batch_items(id),
  target_batch_id TEXT NOT NULL REFERENCES research_batches(id),
  source_batch_id TEXT NOT NULL REFERENCES research_batches(id),
  source_record_id TEXT NOT NULL REFERENCES research_source_records(id),
  interpretation_id TEXT REFERENCES research_interpretations(id),
  metadata_record_id TEXT NOT NULL REFERENCES research_metadata_records(id),
  snapshot_id TEXT NOT NULL REFERENCES research_text_snapshots(id),
  release_id TEXT NOT NULL, reason TEXT NOT NULL,
  validation_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','stale','superseded')),
  operation_id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_research_reuse_binding_active_item
  ON research_reuse_bindings(batch_item_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_research_reuse_source
  ON research_reuse_bindings(source_batch_id,source_record_id,interpretation_id);
CREATE TABLE IF NOT EXISTS research_structure_conversions (
  old_record_id TEXT NOT NULL, layer TEXT NOT NULL,
  new_record_id TEXT NOT NULL PRIMARY KEY,
  report_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_structure_conversions_old
  ON research_structure_conversions(old_record_id);
"""

REQUIRED_TABLES = {
    "research_schema_migrations", "research_sources", "research_text_snapshots",
    "research_source_citations", "research_batches", "research_batch_items", "research_source_records",
    "research_batch_item_events",
    "research_interpretations", "research_claims", "research_evidence",
    "research_review_events", "research_ontology_versions",
    "research_ontology_proposals", "research_ontology_impacts",
    "research_definitions", "research_definition_releases", "research_metadata_records",
    "research_units", "research_feedback", "research_reference_objects",
    "research_cites", "research_task_receipts",
    "research_operation_effects", "research_structure_conversions",
    "research_output_registry",
    "research_source_impacts",
    "research_metadata_tasks", "research_reuse_bindings",
    "research_reference_events",
}
REQUIRED_COLUMNS = {
    "research_source_records": {
        "validation_status", "agent_review_status", "human_adoption_status",
        "validity_status", "updated_at", "layer", "content_state", "release_id",
        "human_adoption_scope_json",
    },
    "research_interpretations": {"validation_status", "layer", "content_state", "release_id",
                                 "human_adoption_scope_json"},
    "research_text_snapshots": {"parse_exists", "parse_quality"},
    "research_batches": {"plan_digest", "environment_id"},
    "research_batch_items": {"worker_owner", "started_at", "heartbeat_at", "lease_expires_at",
                             "recovery_count", "last_recovery_at", "last_recovery_note"},
    "research_review_events": {"record_layer", "record_id", "ontology_proposal_id",
                               "record_version", "basis_json", "event_key"},
    "research_definitions": {"layer", "version", "sha256", "payload_json", "status"},
    "research_definition_releases": {"contract_version", "definition_refs_json"},
    "research_metadata_records": {"work_id", "payload_json", "content_state",
                                  "human_adoption_scope_json"},
    "research_units": {"source_record_id", "unit_key", "payload_json", "content_state",
                       "human_adoption_scope_json"},
    "research_feedback": {"layer", "target_id", "explicit_claim", "status", "resolution_evidence_json"},
    "research_reference_objects": {"external_object_json", "match_status",
                                     "lifecycle_status", "canonical_reference_id",
                                     "correction_json"},
    "research_reference_events": {"reference_id", "action", "actor_id", "event_key",
                                    "reason", "basis_json", "before_json", "after_json"},
    "research_cites": {"citing_work_id", "reference_object_id", "evidence_json"},
    "research_task_receipts": {"operation_id", "task_kind", "result_json", "request_digest"},
    "research_operation_effects": {"operation_id", "seq", "result_json"},
    "research_structure_conversions": {"old_record_id", "layer", "new_record_id", "report_json"},
    "research_output_registry": {"inputs_json", "output_json"},
    "research_source_impacts": {"new_source_record_id", "prior_source_record_id",
                                "interpretation_id", "impacted_unit_keys_json",
                                "change_kind", "requires_rereview"},
    "research_metadata_tasks": {"work_id", "status", "reason", "metadata_record_id",
                                "operation_id", "updated_at"},
    "research_reuse_bindings": {"batch_item_id", "target_batch_id", "source_batch_id",
                                "source_record_id", "interpretation_id", "metadata_record_id",
                                "snapshot_id", "release_id", "reason", "validation_json",
                                "status", "operation_id"},
}
REQUIRED_INDEXES = {
    "idx_research_sources_work", "idx_research_sources_citation",
    "idx_research_source_citations_source", "idx_research_text_snapshot_parse_run",
    "idx_research_batch_items_batch", "idx_research_source_record_state",
    "idx_research_batch_item_events_item",
    "idx_research_interpretation_state", "idx_research_evidence_claim",
    "idx_research_review_record",
    "idx_research_source_impacts_interpretation",
    "idx_research_units_record", "idx_research_units_state",
    "idx_research_feedback_target", "idx_research_reference_match",
    "idx_research_reference_lifecycle", "idx_research_reference_events_ref",
    "idx_research_cites_citing", "idx_research_structure_conversions_old",
    "idx_research_metadata_tasks_status", "idx_research_reuse_source",
    "uq_research_review_event_key", "uq_research_reuse_binding_active_item",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _has_unique_columns(conn: sqlite3.Connection, table: str,
                        expected: tuple[str, ...]) -> bool:
    for row in conn.execute(f"PRAGMA index_list({table})"):
        if row[2] and tuple(item[2] for item in conn.execute(f"PRAGMA index_info({row[1]})")) == expected:
            return True
    return False


def _rebuild_snapshot_lineage(conn: sqlite3.Connection) -> None:
    """Remove the old content-hash uniqueness without changing snapshot ids."""
    cols = _columns(conn, "research_text_snapshots")
    source_cols = _columns(conn, "research_sources")
    parse_exists = ("parse_exists" if "parse_exists" in cols else
                    "COALESCE((SELECT s.parse_exists FROM research_sources s WHERE s.id=research_text_snapshots.source_id),0)"
                    if "parse_exists" in source_cols else "0")
    parse_quality = ("parse_quality" if "parse_quality" in cols else
                     "COALESCE((SELECT s.parse_quality FROM research_sources s WHERE s.id=research_text_snapshots.source_id),'unchecked')"
                     if "parse_quality" in source_cols else "'unchecked'")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript("""
      CREATE TABLE research_text_snapshots_v4 (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES research_sources(id),
        version INTEGER NOT NULL,
        source_file_id TEXT NOT NULL,
        parse_run_id TEXT NOT NULL,
        content_text TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        source_sha256 TEXT NOT NULL,
        parse_exists INTEGER NOT NULL DEFAULT 0 CHECK(parse_exists IN (0,1)),
        parse_quality TEXT NOT NULL DEFAULT 'unchecked'
          CHECK(parse_quality IN ('unchecked','passed','failed')),
        created_at TEXT NOT NULL,
        UNIQUE(source_id,version)
      );
    """)
    conn.execute(f"""INSERT INTO research_text_snapshots_v4
        (id,source_id,version,source_file_id,parse_run_id,content_text,content_sha256,
         source_sha256,parse_exists,parse_quality,created_at)
        SELECT id,source_id,version,source_file_id,parse_run_id,content_text,content_sha256,
               source_sha256,{parse_exists},{parse_quality},created_at
        FROM research_text_snapshots""")
    conn.execute("DROP TABLE research_text_snapshots")
    conn.execute("ALTER TABLE research_text_snapshots_v4 RENAME TO research_text_snapshots")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")


def _upgrade_existing(conn: sqlite3.Connection) -> None:
    """Upgrade the short-lived v1 pilot schema without touching legacy library tables."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if ("research_text_snapshots" in tables and
            _has_unique_columns(conn, "research_text_snapshots", ("source_id", "content_sha256"))):
        _rebuild_snapshot_lineage(conn)
    conn.execute("DROP INDEX IF EXISTS uq_research_text_snapshot_parse_run")
    if "research_text_snapshots" in tables:
        cols = _columns(conn, "research_text_snapshots")
        added_parse_fields = False
        if "parse_exists" not in cols:
            conn.execute("ALTER TABLE research_text_snapshots ADD COLUMN parse_exists INTEGER NOT NULL DEFAULT 0")
            added_parse_fields = True
        if "parse_quality" not in cols:
            conn.execute("ALTER TABLE research_text_snapshots ADD COLUMN parse_quality TEXT NOT NULL DEFAULT 'unchecked'")
            added_parse_fields = True
        if "page_count" not in cols:
            conn.execute("ALTER TABLE research_text_snapshots ADD COLUMN page_count INTEGER")
        if "page_width" not in cols:
            conn.execute("ALTER TABLE research_text_snapshots ADD COLUMN page_width REAL")
        if "page_height" not in cols:
            conn.execute("ALTER TABLE research_text_snapshots ADD COLUMN page_height REAL")
        if "page_sizes" not in cols:
            conn.execute("ALTER TABLE research_text_snapshots ADD COLUMN page_sizes TEXT")
        if "page_offsets" not in cols:
            conn.execute("ALTER TABLE research_text_snapshots ADD COLUMN page_offsets TEXT")
        if added_parse_fields and "research_sources" in tables:
            source_cols = _columns(conn, "research_sources")
            if {"parse_exists", "parse_quality"} <= source_cols:
                conn.execute("""UPDATE research_text_snapshots
                    SET parse_exists=COALESCE((SELECT parse_exists FROM research_sources s WHERE s.id=research_text_snapshots.source_id),0),
                        parse_quality=COALESCE((SELECT parse_quality FROM research_sources s WHERE s.id=research_text_snapshots.source_id),'unchecked')""")
    if "research_batches" in tables and "plan_digest" not in _columns(conn, "research_batches"):
        conn.execute("ALTER TABLE research_batches ADD COLUMN plan_digest TEXT NOT NULL DEFAULT ''")
    if "research_batch_items" in tables:
        cols = _columns(conn, "research_batch_items")
        for name in ("worker_owner", "started_at", "heartbeat_at", "lease_expires_at"):
            if name not in cols:
                conn.execute(f"ALTER TABLE research_batch_items ADD COLUMN {name} TEXT")
        if "recovery_count" not in cols:
            conn.execute("ALTER TABLE research_batch_items ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0")
        for name in ("last_recovery_at", "last_recovery_note"):
            if name not in cols:
                conn.execute(f"ALTER TABLE research_batch_items ADD COLUMN {name} TEXT")
    if "research_source_records" in tables:
        cols = _columns(conn, "research_source_records")
        additions = {
            "validation_status": "TEXT NOT NULL DEFAULT 'passed'",
            "agent_review_status": "TEXT NOT NULL DEFAULT 'pending'",
            "human_adoption_status": "TEXT NOT NULL DEFAULT 'pending'",
            "validity_status": "TEXT NOT NULL DEFAULT 'active'",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for name, declaration in additions.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE research_source_records ADD COLUMN {name} {declaration}")
        conn.execute("UPDATE research_source_records SET updated_at=created_at WHERE updated_at='' ")
    if "research_interpretations" in tables and "validation_status" not in _columns(conn, "research_interpretations"):
        conn.execute("ALTER TABLE research_interpretations ADD COLUMN validation_status TEXT NOT NULL DEFAULT 'passed'")
    if "research_review_events" in tables:
        cols = _columns(conn, "research_review_events")
        if "record_layer" not in cols or "record_id" not in cols:
            conn.execute("ALTER TABLE research_review_events RENAME TO research_review_events_v1")
            conn.execute("""CREATE TABLE research_review_events (
                id TEXT PRIMARY KEY, record_layer TEXT NOT NULL, record_id TEXT NOT NULL,
                actor_type TEXT NOT NULL, decision TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL
            )""")
            conn.execute("""INSERT INTO research_review_events
                (id,record_layer,record_id,actor_type,decision,note,created_at)
                SELECT id,'interpretation',interpretation_id,actor_type,decision,note,created_at
                FROM research_review_events_v1""")
            conn.execute("DROP TABLE research_review_events_v1")
            cols = _columns(conn, "research_review_events")
        if "ontology_proposal_id" not in cols:
            conn.execute("ALTER TABLE research_review_events ADD COLUMN ontology_proposal_id TEXT")
    # ----- v5: envelope columns, content three-states, environment binding -----
    if "research_batches" in tables and "environment_id" not in _columns(conn, "research_batches"):
        conn.execute("ALTER TABLE research_batches ADD COLUMN environment_id TEXT")
    if "research_batches" in tables and "plan_targets_json" not in _columns(conn, "research_batches"):
        conn.execute("ALTER TABLE research_batches ADD COLUMN plan_targets_json TEXT")
    # B5: a batch is pinned to the definition release active at plan time so
    # task packages, submissions and reconciliations consume the SAME bundle.
    if "research_batches" in tables and "release_id" not in _columns(conn, "research_batches"):
        conn.execute("ALTER TABLE research_batches ADD COLUMN release_id TEXT")
    if "research_task_receipts" in tables and \
            "request_digest" not in _columns(conn, "research_task_receipts"):
        conn.execute("ALTER TABLE research_task_receipts ADD COLUMN request_digest TEXT")
    # B1/B4(R6): a receipt is bound to the environment that earned it — a
    # replay must not return a success recorded against another store.
    if "research_task_receipts" in tables and \
            "environment_id" not in _columns(conn, "research_task_receipts"):
        conn.execute("ALTER TABLE research_task_receipts ADD COLUMN environment_id TEXT")
    # B2: a retained_with_evidence closure must keep its machine-checkable evidence
    if "research_feedback" in tables and \
            "resolution_evidence_json" not in _columns(conn, "research_feedback"):
        conn.execute("ALTER TABLE research_feedback ADD COLUMN resolution_evidence_json TEXT")
    # B6: scoped human adoption is recorded on the record, not only on events
    for _scoped_table in ("research_source_records", "research_interpretations",
                          "research_metadata_records", "research_units"):
        if _scoped_table in tables and \
                "human_adoption_scope_json" not in _columns(conn, _scoped_table):
            conn.execute(f"ALTER TABLE {_scoped_table} ADD COLUMN human_adoption_scope_json TEXT")
    # B2: generation origin is pinned on the record/version at submit time so
    # reviewer independence never depends on the current batch-item claim holder.
    for _scoped_table in ("research_source_records", "research_interpretations",
                          "research_metadata_records", "research_units"):
        if _scoped_table in tables and \
                "submitted_by" not in _columns(conn, _scoped_table):
            conn.execute(f"ALTER TABLE {_scoped_table} ADD COLUMN submitted_by TEXT")
    # U24: an interpretation pins the metadata record it actually consumed so
    # later openness changes can be traced to the dependent interpretations.
    if "research_interpretations" in tables and \
            "source_metadata_record_id" not in _columns(conn, "research_interpretations"):
        conn.execute("ALTER TABLE research_interpretations ADD COLUMN source_metadata_record_id TEXT")
    # B9: catalog propagation state is PERSISTED on the record so a failure
    # stays visible and retryable across refresh/restart, not only in the
    # response that happened to carry it.
    if "research_metadata_records" in tables and             "propagation_state_json" not in _columns(conn, "research_metadata_records"):
        conn.execute("ALTER TABLE research_metadata_records ADD COLUMN propagation_state_json TEXT")
    # B7/U24: new outputs keep the actual emitted content, not only mutable
    # row identifiers.  Existing registry rows remain explicit legacy entries
    # with output_json=NULL; future emissions are independently retrievable.
    if "research_output_registry" in tables and \
            "output_json" not in _columns(conn, "research_output_registry"):
        conn.execute("ALTER TABLE research_output_registry ADD COLUMN output_json TEXT")
    if "research_review_events" in tables:
        event_cols = _columns(conn, "research_review_events")
        if "scope_json" not in event_cols:
            conn.execute("ALTER TABLE research_review_events ADD COLUMN scope_json TEXT")
        if "actor_id" not in event_cols:
            conn.execute("ALTER TABLE research_review_events ADD COLUMN actor_id TEXT")
        if "record_version" not in event_cols:
            conn.execute("ALTER TABLE research_review_events ADD COLUMN record_version INTEGER")
        if "basis_json" not in event_cols:
            conn.execute("ALTER TABLE research_review_events ADD COLUMN basis_json TEXT")
        if "event_key" not in event_cols:
            conn.execute("ALTER TABLE research_review_events ADD COLUMN event_key TEXT")
    if "research_reference_objects" in tables:
        reference_cols = _columns(conn, "research_reference_objects")
        if "lifecycle_status" not in reference_cols:
            conn.execute(
                "ALTER TABLE research_reference_objects ADD COLUMN lifecycle_status "
                "TEXT NOT NULL DEFAULT 'active'")
        if "canonical_reference_id" not in reference_cols:
            conn.execute(
                "ALTER TABLE research_reference_objects ADD COLUMN canonical_reference_id TEXT")
        if "correction_json" not in reference_cols:
            conn.execute("ALTER TABLE research_reference_objects ADD COLUMN correction_json TEXT")
    # Conservative content-state backfill: migrated records are never stable.
    # needs_review unless structural validation or evidence is incomplete.
    if "research_source_records" in tables:
        cols = _columns(conn, "research_source_records")
        if "layer" not in cols:
            conn.execute("ALTER TABLE research_source_records ADD COLUMN layer TEXT NOT NULL DEFAULT 'source_record'")
        for name in ("release_id", "definition_refs_json", "scope_json", "feedback_id"):
            if name not in cols:
                conn.execute(f"ALTER TABLE research_source_records ADD COLUMN {name} TEXT")
        if "content_state" not in cols:
            conn.execute(
                "ALTER TABLE research_source_records ADD COLUMN content_state TEXT NOT NULL DEFAULT 'needs_review'"
                )
    if "research_interpretations" in tables:
        cols = _columns(conn, "research_interpretations")
        if "layer" not in cols:
            conn.execute("ALTER TABLE research_interpretations ADD COLUMN layer TEXT NOT NULL DEFAULT 'interpretation'")
        for name in ("release_id", "definition_refs_json", "scope_json", "feedback_id"):
            if name not in cols:
                conn.execute(f"ALTER TABLE research_interpretations ADD COLUMN {name} TEXT")
        if "content_state" not in cols:
            conn.execute(
                "ALTER TABLE research_interpretations ADD COLUMN content_state TEXT NOT NULL DEFAULT 'needs_review'"
                )


def _conv_id(prefix: str) -> str:
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _convert_legacy_source_payload(old: dict) -> tuple[dict, list[str], list[str]]:
    """Deterministic v1→v5 source-record mapping.

    Inherits what is technically decidable (unit names, per-unit conditions);
    everything that needs a human/agent semantic decision (author definitions,
    coverage statements, observations) is preserved verbatim under
    ``legacy_fields`` and listed as needing recheck — never dropped, never invented.
    """
    coverage = old.get("coverage") or {}
    unit_names = [str(u).strip() for u in coverage.get("units") or [] if str(u).strip()]
    cond_by_unit: dict[str, list] = {}
    shared_conditions: list = []
    for cond in old.get("conditions") or []:
        if not isinstance(cond, dict):
            shared_conditions.append({"content": cond})
            continue
        unit = str(cond.get("unit") or "").strip()
        if unit:
            cond_by_unit.setdefault(unit, []).append(cond)
        else:
            shared_conditions.append(cond)
    units = [{
        "unit_key": name,
        "conditions": cond_by_unit.get(name, []),
    } for name in unit_names]
    inherited = [f"units[].unit_key={name}" for name in unit_names]
    inherited += [f"units[{name}].conditions" for name in unit_names if cond_by_unit.get(name)]
    shared_items = [{"key": f"legacy-condition-{index}", "content": cond,
                     "source": "legacy-conversion"}
                    for index, cond in enumerate(shared_conditions)]
    gaps = []
    if units:
        gaps.append({"key": "author-definitions",
                     "detail": "v1 记录未按当前发布定义抽取逐字作者定义/操作化判据；"
                               "各单元回查原文补全后才能进入核查，未补全前不得 stable。"})
    needs_recheck = sorted(set(old) - {"coverage", "conditions"})
    payload = {
        "record_mode": "units" if units else "not_applicable",
        "units": units,
        "shared_items": shared_items,
        "gaps": gaps,
        "legacy_fields": {key: old[key] for key in needs_recheck},
        "extensions": [{
            "name": "legacy-conversion",
            "content": {
                "legacy_schema_version": "source-record-v1",
                "inherited_fields": inherited,
                "needs_recheck_fields": needs_recheck + (["units[].definitions"] if units else []),
                "note": "确定性技术转换；语义字段须在当前发布定义下回查补全，"
                        "未补全前不得 stable。",
            },
            "source": "apply_schema 结构转换",
            "scope": "record",
            "needs_verification": True,
        }],
    }
    if not units:
        payload["gaps"] = gaps or [{"key": "record-mode-basis",
                                    "detail": "v1 记录无单元清单；record_mode 需人工确认。"}]
    return payload, inherited, needs_recheck


def _convert_legacy_interpretation_payload(old: dict, valid_keys: set[str]) -> tuple[dict, list[str], list[str]]:
    """Deterministic v1→v5 interpretation mapping (same honesty rules as C)."""
    inherited: list[str] = []
    payload: dict = {}
    for field in ("update_object", "research_role", "mapping_status", "deployment_condition",
                  "reasoning", "unresolved"):
        if field in old:
            payload[field] = old[field]
            inherited.append(field)
    old_keys = old.get("risk_phenomena") or []
    keys = [key for key in old_keys if key in valid_keys]
    payload["ontology_keys"] = keys
    payload["scope"] = {"input_refs": [], "work_scope": None,
                        "conditions": old.get("conditions") or []}
    needs_recheck = ["statement", "support_boundary", "scope.input_refs"]
    legacy_field_names = sorted(set(old) - {"update_object", "research_role", "mapping_status",
                                            "deployment_condition", "reasoning", "unresolved",
                                            "risk_phenomena", "conditions"})
    payload["legacy_fields"] = {key: old[key] for key in legacy_field_names}
    payload["extensions"] = [{
        "name": "legacy-conversion",
        "content": {
            "legacy_schema_version": "interpretation-v1",
            "inherited_fields": inherited + [f"ontology_keys({len(keys)})"],
            "needs_recheck_fields": needs_recheck,
            "dropped_from_ontology_keys": sorted(set(old_keys) - set(keys)),
            "note": "确定性技术转换；命题/支持边界/输入范围须重新表达后才能进入核查。",
        },
        "source": "apply_schema 结构转换",
        "scope": "record",
        "needs_verification": True,
    }]
    return payload, inherited, needs_recheck


def _copy_record_claims(conn: sqlite3.Connection, layer: str, old_id: str, new_id: str) -> int:
    """Copy claims + evidence to the converted record under fresh ids."""
    rows = conn.execute(
        "SELECT id,claim_key,claim_text FROM research_claims WHERE record_layer=? AND record_id=?",
        (layer, old_id),
    ).fetchall()
    now = _now()
    total = 0
    for claim in rows:
        new_claim_id = _conv_id("RC")
        conn.execute(
            "INSERT INTO research_claims(id,record_layer,record_id,claim_key,claim_text,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (new_claim_id, layer, new_id, claim["claim_key"], claim["claim_text"], now),
        )
        evidence_rows = conn.execute(
            """SELECT snapshot_id,quote,start_offset,end_offset,locator_json
               FROM research_evidence WHERE claim_id=?""",
            (claim["id"],),
        ).fetchall()
        # one fresh id per evidence row — a single INSERT..SELECT would stamp
        # the same id onto every copied row and break the UNIQUE constraint
        for evidence in evidence_rows:
            conn.execute(
                """INSERT INTO research_evidence
                   (id,claim_id,snapshot_id,quote,start_offset,end_offset,locator_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_conv_id("RE"), new_claim_id, evidence["snapshot_id"], evidence["quote"],
                 evidence["start_offset"], evidence["end_offset"], evidence["locator_json"], now),
            )
        total += 1
    return total


def _fk_orphan_reason(conn: sqlite3.Connection, row: sqlite3.Row, checks) -> str | None:
    """Conservative B8 guard: a legacy row whose structural references no
    longer resolve cannot be rebuilt on the current structure.  It stays
    frozen as-is (needs_completion, never stable) and is reported, instead of
    crashing the whole schema apply on one orphan row."""
    for table, column in checks:
        value = row[column]
        if value is not None and not conn.execute(
                f"SELECT 1 FROM {table} WHERE id=?", (value,)).fetchone():
            return f"{column} {value} not found"
    return None


_SOURCE_ORPHAN_CHECKS = (("research_batches", "batch_id"),
                         ("research_sources", "source_id"),
                         ("research_text_snapshots", "snapshot_id"))
_INTERPRETATION_ORPHAN_CHECKS = (("research_batches", "batch_id"),
                                 ("research_sources", "source_id"),
                                 ("research_source_records", "source_record_id"),
                                 ("research_text_snapshots", "snapshot_id"))


def _convert_legacy_structures(conn: sqlite3.Connection, release: dict, now: str) -> dict:
    """B8: rebuild legacy (pre-release) C/D rows on the current structure.

    One current structure: every legacy record gets a new revision bound to the
    released definition bundle, with deterministic fields inherited, semantic
    fields explicitly listed for recheck, content frozen at needs_completion
    (never stable), and the old row kept queryable but superseded.  Idempotent
    through ``research_structure_conversions``.
    """
    report: dict = {"source_records": [], "interpretations": [],
                    "skipped_already_converted": 0, "fk_orphans": []}
    refs_json = json.dumps(release["definition_refs"], ensure_ascii=False)
    done_old = {r[0] for r in conn.execute(
        "SELECT old_record_id FROM research_structure_conversions")}
    ref_by_layer = {r["layer"]: r for r in release["definition_refs"]}
    sr_definition = _definition_payload(conn, ref_by_layer["source_record"]["definition"])
    in_definition = _definition_payload(conn, ref_by_layer["interpretation"]["definition"])
    valid_concepts: set[str] = set()
    for (payload_json,) in conn.execute("SELECT payload_json FROM research_ontology_versions"):
        payload = json.loads(payload_json)
        for concept in payload.get("concepts") or []:
            if isinstance(concept, dict):
                key = concept.get("id") or concept.get("key")
                if key:
                    valid_concepts.add(str(key))

    def _insert_conversion(old_id: str, layer: str, new_id: str, entry: dict) -> None:
        conn.execute(
            """INSERT INTO research_structure_conversions
               (old_record_id,layer,new_record_id,report_json,created_at) VALUES (?,?,?,?,?)""",
            (old_id, layer, new_id, json.dumps(entry, ensure_ascii=False), now))

    source_id_map: dict[str, str] = {}
    legacy_sources = conn.execute(
        """SELECT * FROM research_source_records WHERE release_id IS NULL ORDER BY batch_id,source_id,version"""
    ).fetchall()
    for row in legacy_sources:
        if row["id"] in done_old:
            report["skipped_already_converted"] += 1
            continue
        orphan = _fk_orphan_reason(conn, row, _SOURCE_ORPHAN_CHECKS)
        if orphan:
            report["fk_orphans"].append(
                {"layer": "source_record", "old_record_id": row["id"], "detail": orphan})
            continue
        old_payload = json.loads(row["payload_json"])
        new_payload, inherited, needs_recheck = _convert_legacy_source_payload(old_payload)
        version = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM research_source_records WHERE batch_id=? AND source_id=?",
            (row["batch_id"], row["source_id"])).fetchone()[0]
        new_id = _conv_id("RSR")
        # B8: historical validity carries over.  A stale/superseded legacy
        # version must not re-emerge as an active needs_completion candidate
        # on the current structure — only the genuinely active head converts
        # to the active re-expression candidate.
        converted_validity = row["validity_status"] if row["validity_status"] in (
            "active", "stale", "superseded") else "active"
        conn.execute(
            """INSERT INTO research_source_records
            (id,batch_id,source_id,source_file_id,parse_run_id,snapshot_id,snapshot_sha256,
             schema_version,version,payload_json,validation_status,agent_review_status,
             human_adoption_status,validity_status,supersedes_id,layer,content_state,
             release_id,definition_refs_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,'pending','pending','pending',?,?,
                    'source_record','needs_completion',?,?,?,?)""",
            (new_id, row["batch_id"], row["source_id"], row["source_file_id"], row["parse_run_id"],
             row["snapshot_id"], row["snapshot_sha256"],
             sr_definition.get("version", "source-record-v5.1"),
             version, json.dumps(new_payload, ensure_ascii=False),
             converted_validity, row["id"], release["id"],
             refs_json, now, now))
        conn.execute(
            "UPDATE research_source_records SET validity_status='superseded',updated_at=? WHERE id=?",
            (now, row["id"]))
        _copy_record_claims(conn, "source_record", row["id"], new_id)
        conn.execute(
            "UPDATE research_batch_items SET source_record_id=?,updated_at=? "
            "WHERE batch_id=? AND source_record_id=?",
            (new_id, now, row["batch_id"], row["id"]))
        entry = {"old_record_id": row["id"], "new_record_id": new_id,
                 "schema_version": sr_definition.get("version", "source-record-v5.1"),
                 "release_id": release["id"], "content_state": "needs_completion",
                 "inherited_fields": inherited, "needs_recheck_fields": needs_recheck}
        _insert_conversion(row["id"], "source_record", new_id, entry)
        report["source_records"].append(entry)
        source_id_map[row["id"]] = new_id

    legacy_ints = conn.execute(
        """SELECT * FROM research_interpretations WHERE release_id IS NULL ORDER BY batch_id,source_record_id,version"""
    ).fetchall()
    for row in legacy_ints:
        if row["id"] in done_old:
            report["skipped_already_converted"] += 1
            continue
        orphan = _fk_orphan_reason(conn, row, _INTERPRETATION_ORPHAN_CHECKS)
        if orphan:
            report["fk_orphans"].append(
                {"layer": "interpretation", "old_record_id": row["id"], "detail": orphan})
            continue
        new_source_record_id = source_id_map.get(row["source_record_id"])
        if not new_source_record_id:
            head = conn.execute(
                """SELECT id FROM research_source_records WHERE batch_id=? AND source_id=?
                   AND release_id IS NOT NULL ORDER BY version DESC LIMIT 1""",
                (row["batch_id"], row["source_id"])).fetchone()
            new_source_record_id = head["id"] if head else row["source_record_id"]
        old_payload = json.loads(row["payload_json"])
        new_payload, inherited, needs_recheck = _convert_legacy_interpretation_payload(
            old_payload, valid_concepts)
        row_keys = json.loads(row["ontology_keys_json"] or "[]")
        keys = sorted(set(row_keys) & valid_concepts)
        version = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM research_interpretations WHERE batch_id=? AND source_record_id=?",
            (row["batch_id"], new_source_record_id)).fetchone()[0]
        new_id = _conv_id("RI")
        # B8: carry the legacy row's validity (see the source-record branch) —
        # an expired version must not re-emerge as an active candidate.
        converted_validity = row["validity_status"] if row["validity_status"] in (
            "active", "stale", "superseded") else "active"
        conn.execute(
            """INSERT INTO research_interpretations
            (id,batch_id,source_record_id,source_id,source_file_id,parse_run_id,snapshot_id,
             snapshot_sha256,ontology_version,ontology_keys_json,schema_version,version,payload_json,
             validation_status,agent_review_status,human_adoption_status,validity_status,
             supersedes_id,layer,content_state,release_id,definition_refs_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'pending','pending','pending',?,?,
                    'interpretation','needs_completion',?,?,?,?)""",
            (new_id, row["batch_id"], new_source_record_id, row["source_id"], row["source_file_id"],
             row["parse_run_id"], row["snapshot_id"], row["snapshot_sha256"],
             row["ontology_version"], json.dumps(keys, ensure_ascii=False),
             in_definition.get("version", "interpretation-v5"),
             version, json.dumps(new_payload, ensure_ascii=False),
             converted_validity, row["id"], release["id"],
             refs_json, now, now))
        conn.execute(
            "UPDATE research_interpretations SET validity_status='superseded',updated_at=? WHERE id=?",
            (now, row["id"]))
        _copy_record_claims(conn, "interpretation", row["id"], new_id)
        conn.execute(
            "UPDATE research_batch_items SET interpretation_id=?,updated_at=? "
            "WHERE batch_id=? AND interpretation_id=?",
            (new_id, now, row["batch_id"], row["id"]))
        entry = {"old_record_id": row["id"], "new_record_id": new_id,
                 "schema_version": in_definition.get("version", "interpretation-v5"),
                 "release_id": release["id"], "content_state": "needs_completion",
                 "inherited_fields": inherited, "needs_recheck_fields": needs_recheck}
        _insert_conversion(row["id"], "interpretation", new_id, entry)
        report["interpretations"].append(entry)
    return report


def _definition_payload(conn: sqlite3.Connection, definition_id: str) -> dict:
    row = conn.execute("SELECT payload_json FROM research_definitions WHERE id=?",
                       (definition_id,)).fetchone()
    return json.loads(row[0]) if row else {}


def _backfill_content_states(conn: sqlite3.Connection) -> dict:
    """Mark structurally/structurally-legacy incomplete records needs_completion.
    Never sets stable.  Idempotent and conservative:
    - validation failed or no evidence-backed claims → needs_completion;
    - legacy structure (no release binding, i.e. records written before the
      four-layer definitions) → needs_completion: legacy content must be
      re-expressed under a released definition before it can become stable.
    """
    report: dict[str, int] = {}
    for table in ("research_source_records", "research_interpretations"):
        cols = _columns(conn, table)
        claim_layer = "source_record" if table == "research_source_records" else "interpretation"
        if "content_state" not in cols:
            report[table] = 0
            continue
        legacy_clause = ""
        params: list = []
        if "release_id" in cols:
            legacy_clause = " OR release_id IS NULL"
        if "validation_status" in cols:
            legacy_clause = "(validation_status!='passed'" + legacy_clause + ")"
        else:
            legacy_clause = "(1=1" + legacy_clause + ")"
        cur = conn.execute(
            f"""UPDATE {table} SET content_state='needs_completion'
                WHERE content_state!='stable' AND ({legacy_clause} OR id NOT IN
                  (SELECT DISTINCT record_id FROM research_claims WHERE record_layer=?))""",
            (*params, claim_layer),
        )
        report[table] = cur.rowcount
    return report


def migration_plan(ctx: ResearchContext) -> dict:
    if not ctx.db_path.exists():
        existing: set[str] = set()
    else:
        ro = ResearchContext(ctx.library_root, ctx.db_path, True)
        with closing(ro.connect()) as conn:
            existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {
        "apply": False,
        "db_path": str(ctx.db_path),
        "schema_version": SCHEMA_VERSION,
        "existing_tables": sorted(existing & REQUIRED_TABLES),
        "missing_tables": sorted(REQUIRED_TABLES - existing),
    }


def backup_database(ctx: ResearchContext, destination: Path | None = None) -> Path | None:
    if not ctx.db_path.exists() or ctx.db_path.stat().st_size == 0:
        return None
    if destination is None:
        # A per-second timestamp alone is NOT unique: restore_database takes a
        # pre-restore safety backup that could land in the same second and
        # silently OVERWRITE the backup being restored — the "newer writes"
        # guard would then compare the database against itself and wave a
        # destructive restore through.  A random suffix keeps every backup a
        # distinct file.
        import uuid
        destination = (
            ctx.library_root / "_research_backups" /
            f"research-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            f"-{uuid.uuid4().hex[:6]}.sqlite"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(
            f"backup destination already exists: {destination}; "
            "backups are append-only — pass a fresh path instead of overwriting")
    with closing(ctx.connect(read_only=True)) as src, closing(sqlite3.connect(str(destination))) as dst:
        src.backup(dst)
    return destination


def apply_schema(ctx: ResearchContext, *, backup: bool = True) -> dict:
    from .research_definitions import seed_definitions_and_release

    ctx.require_writable()
    backup_path = backup_database(ctx) if backup else None
    with closing(ctx.connect()) as conn:
        _upgrade_existing(conn)
        conn.executescript(SCHEMA_SQL)
        conversion = _backfill_content_states(conn)
        from .research_runtime_assets import asset_path
        baseline = json.loads(asset_path('baseline').read_text(encoding='utf-8'))
        now = _now()
        conn.execute(
            "INSERT OR IGNORE INTO research_ontology_versions(version,parent_version,status,payload_json,created_at,published_at) VALUES (?,?,?,?,?,?)",
            (baseline["version"], None, "baseline", json.dumps(baseline, ensure_ascii=False), now, now),
        )
        seed_result = seed_definitions_and_release(conn, contract_version=int(CONTRACT["version"]), now=now)
        structure = _convert_legacy_structures(
            conn, {"id": seed_result["release_id"], "definition_refs": seed_result["definition_refs"]}, now)
        conn.execute(
            "INSERT OR REPLACE INTO research_schema_migrations(version,contract_version,applied_at) VALUES (?,?,?)",
            (SCHEMA_VERSION, int(CONTRACT["version"]), now),
        )
        conn.commit()
    result = verify_schema(ctx)
    result["backup_path"] = str(backup_path) if backup_path else None
    result["conversion_report"] = {
        "marked_needs_completion": conversion,
        "structure_conversion": structure,
        "rule": "旧结构（无发布包绑定）/校验失败/无证据主张的记录一律 needs_completion，"
                "须在当前发布定义下重新表达并重审后才可 stable；迁移绝不自动 stable；"
                "旧结构记录经确定性技术转换重建为绑定发布包的新版本，"
                "可继承字段与须回查字段在转换报告中分明列出，旧内容冻结可查。",
    }
    return result


def verify_schema(ctx: ResearchContext) -> dict:
    if not ctx.db_path.exists():
        return {"ok": False, "missing_tables": sorted(REQUIRED_TABLES),
                "missing_columns": {}, "missing_indexes": sorted(REQUIRED_INDEXES),
                "schema_version": None, "foreign_key_errors": []}
    with closing(ctx.connect(read_only=True)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        row = conn.execute("SELECT MAX(version) FROM research_schema_migrations").fetchone() if "research_schema_migrations" in tables else None
        version = row[0] if row else None
        fk_errors = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")] if REQUIRED_TABLES <= tables else []
        missing_columns = {
            table: sorted(required - _columns(conn, table))
            for table, required in REQUIRED_COLUMNS.items()
            if table in tables and required - _columns(conn, table)
        }
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        missing_indexes = sorted(REQUIRED_INDEXES - indexes)
    missing = sorted(REQUIRED_TABLES - tables)
    return {"ok": not missing and not missing_columns and not missing_indexes and not fk_errors and version == SCHEMA_VERSION,
            "missing_tables": missing, "missing_columns": missing_columns,
            "missing_indexes": missing_indexes,
            "schema_version": version, "foreign_key_errors": fk_errors}


def _newer_rows(current_db: Path, backup_db: Path, cutoff: str | None) -> dict[str, list[dict]]:
    """Rows inserted after the backup was taken, per timestamped table.

    Used to protect writes that happened after a backup was taken: a restore
    must never silently destroy them.  ``created_at`` has seconds resolution,
    so same-second writes are detected by count: a post-backup INSERT either
    lands after the cutoff or increases the count of rows sitting exactly on it.
    """
    affected: dict[str, list[dict]] = {}
    if not cutoff:
        return affected
    with closing(ctx_ro(current_db).connect()) as cur, closing(ctx_ro(backup_db).connect()) as bak:
        tables = [r[0] for r in bak.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'research_%'")]
        for table in tables:
            if "created_at" not in _columns(bak, table):
                continue
            if table not in [r[0] for r in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'research_%'")]:
                continue
            try:
                rows = cur.execute(
                    f"SELECT * FROM \"{table}\" WHERE created_at>? ORDER BY created_at",
                    (cutoff,),
                ).fetchall()
                ties_backup = bak.execute(
                    f"SELECT COUNT(*) FROM \"{table}\" WHERE created_at=?", (cutoff,)).fetchone()[0]
                ties_current = cur.execute(
                    f"SELECT COUNT(*) FROM \"{table}\" WHERE created_at=?", (cutoff,)).fetchone()[0]
                if ties_current > ties_backup:
                    rows.extend(cur.execute(
                        f"SELECT * FROM \"{table}\" WHERE created_at=? ORDER BY rowid DESC LIMIT ?",
                        (cutoff, ties_current - ties_backup)).fetchall())
            except sqlite3.OperationalError:
                continue
            if rows:
                affected[table] = [dict(r) for r in rows]
    return affected


def ctx_ro(db_path: Path) -> ResearchContext:
    return ResearchContext(db_path.parent, db_path, read_only=True)


def restore_database(ctx: ResearchContext, backup_path: Path, *, force: bool = False) -> dict:
    """Restore from a backup, protecting writes made after the backup.

    Refuses when the current database holds rows newer than the backup's newest
    row (a switch-era write would be destroyed) unless ``force=True``; with
    force, the destroyed rows are dumped to a JSON sidecar next to the backup
    so nothing disappears without a trace.
    """
    ctx.require_writable()
    backup_path = backup_path.resolve()
    if not backup_path.is_file():
        raise FileNotFoundError(backup_path)
    safety = backup_database(ctx)
    backup_cutoff: str | None = None
    with closing(ctx_ro(backup_path).connect()) as conn:
        # the cutoff is the backup's own newest write across every timestamped
        # table — research_schema_migrations only records schema applies
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'research_%'")]
        for table in tables:
            if "created_at" not in _columns(conn, table):
                continue
            row = conn.execute(f"SELECT MAX(created_at) FROM \"{table}\"").fetchone()
            if row and row[0] and (backup_cutoff is None or row[0] > backup_cutoff):
                backup_cutoff = row[0]
    newer = _newer_rows(ctx.db_path, backup_path, backup_cutoff)
    newer_count = sum(len(rows) for rows in newer.values())
    if newer_count and not force:
        return {"restored": False, "refused": True,
                "newer_rows": newer_count,
                "newer_tables": sorted(newer),
                "note": "检测到备份之后新增的写入；默认拒绝恢复以免破坏切换后的新内容。"
                        "确认放弃这些写入时以 force=True 重试，销毁行会先落盘留档。",
                "pre_restore_backup": str(safety) if safety else None}
    destroyed_dump = None
    if newer_count:
        destroyed_dump = backup_path.with_name(
            backup_path.stem + f"-destroyed-on-restore-{_now().replace(':', '')}.json")
        destroyed_dump.write_text(json.dumps(
            {"backup": str(backup_path), "cutoff": backup_cutoff, "rows": newer},
            ensure_ascii=False, indent=2), encoding="utf-8")
    with closing(sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)) as src, closing(ctx.connect()) as dst:
        src.backup(dst)
    result = verify_schema(ctx)
    result.update({"restored": True, "force": force,
                   "newer_rows_destroyed": newer_count,
                   "destroyed_rows_dump": str(destroyed_dump) if destroyed_dump else None,
                   "pre_restore_backup": str(safety) if safety else None})
    return result
