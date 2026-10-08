"""HTTP adapter for the isolated research workflow."""
from __future__ import annotations

import json
import logging
import os

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..research_context import get_research_context, REPO_ROOT
from ..research_drafts import ResearchDraftStore
from ..research_errors import ResearchOperationError
from ..research_next import ResearchNextService
from ..research_parse_corrections import ParseCorrectionService
from ..research_schema import migration_plan, verify_schema, compute_environment_id
from ..research_service import ResearchConflictError, ResearchService

router = APIRouter()

@router.get('/research/runtime-assets')
def runtime_presentation_assets():
    from ..research_runtime_assets import presentation_assets
    return _call(presentation_assets)


def _svc() -> ResearchService:
    return ResearchService(get_research_context())


def _next() -> ResearchNextService:
    return ResearchNextService(get_research_context())


def _drafts() -> ResearchDraftStore:
    return ResearchDraftStore(get_research_context())


def _draft_call(method, *args, **kwargs):
    # Constructor guards belong inside the same HTTP error boundary as methods.
    return _call(lambda: getattr(_drafts(), method)(*args, **kwargs))


def _pcorr() -> ParseCorrectionService:
    return ParseCorrectionService(get_research_context())


_ERROR_STATUS = {
    "invalid_payload": 400,
    "incompatible_definition": 409,
    "identity_conflict": 409,
    "revision_conflict": 409,
    "lease_conflict": 409,
    "dependency_unavailable": 503,
    "read_only": 409,
    "not_found": 404,
    "retryable_failure": 503,
}


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ResearchConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ResearchOperationError as exc:
        raise HTTPException(_ERROR_STATUS[exc.category], exc.to_dict()) from exc
    except (ValueError, PermissionError, RuntimeError, FileNotFoundError, FileExistsError) as exc:
        raise HTTPException(409 if isinstance(exc, PermissionError) else 400, str(exc)) from exc


class SourceImport(BaseModel):
    source_path: str
    text: str
    work_id: str | None = None
    source_file_id: str | None = None
    parse_run_id: str | None = None
    citation_key: str | None = None
    citation_keys: list[str] = Field(default_factory=list)
    parse_quality: str = "unchecked"
    # U19: material geometry travels with the parse so locator claims
    # (page bounds, figure regions) are checkable at submission time.
    page_count: int | None = None
    page_width: float | None = None
    page_height: float | None = None
    page_sizes: list[dict[str, Any]] | None = None
    page_offsets: list[int] | None = None


class BatchPlan(BaseModel):
    request_key: str
    name: str
    source_ids: list[str]
    snapshot_ids: dict[str, str] | None = None
    ontology_version: str = "autonomy-risk-v1"
    rerun: bool = False
    # A7: axis/scope contract this plan commits to (stored as plan_targets_json)
    targets: dict[str, Any] | None = None
    # B5(R6): the release the plan pins (defaults to the current bundle)
    release_id: str | None = None


class WorkStageRequest(BaseModel):
    """New-material relay (LL-DECOUPLE-20260920 §4.3; R1 B3 adds existing_batch).

    ``batch_mode``:
    - ``import_only``: stage the work's successful parse into the research
      store; batch planning stays with the research view.
    - ``new_batch``: additionally plan a fresh batch containing this source so
      the v5 agent flow (task package → records → review) can start at once.
    - ``existing_batch``: relay the source into the batch identified by
      ``batch_id``.  v5 batches are immutable plans, so this creates the
      lineage's next round (parent_batch_id set, release pin inherited)
      carrying the previous items plus this source — never an in-place
      append, never a standalone single-work batch.  Idempotent per lineage.
    """
    batch_mode: str = "import_only"
    batch_name: str | None = None
    request_key: str | None = None
    batch_id: str | None = None


def _latest_successful_parse(work_id: str):
    from contextlib import closing

    from ..db import get_conn
    with closing(get_conn()) as conn:
        work = conn.execute("SELECT id FROM works WHERE id=?", (work_id,)).fetchone()
        if not work:
            raise HTTPException(404, f"work {work_id} not found in catalog")
        run = conn.execute(
            """SELECT pr.*, sf.source_path AS sf_source_path, sf.id AS sf_id
               FROM literature_parse_runs pr
               JOIN source_files sf ON sf.id = pr.source_file_id
               WHERE pr.work_id=? AND pr.status='succeeded'
                 AND COALESCE(pr.content_md_path,'') != ''
               ORDER BY COALESCE(pr.finished_at, pr.started_at) DESC, pr.id DESC
               LIMIT 1""", (work_id,)).fetchone()
        return dict(run) if run else None


@router.post("/research/works/{work_id}/stage")
def stage_work(work_id: str, body: WorkStageRequest):
    """Relay a successfully parsed work into the research store (v5 path).

    This is the new-material main path: no legacy metadata/classification
    extraction is required or consulted.  Idempotent — restaging a work whose
    source_file_id is already imported returns the existing source/snapshot.
    """
    from ..storage.runtime import enabled as immutable_enabled
    if immutable_enabled():
        raise HTTPException(409, 'Immutable materials require an explicit fixed source/parse/version import; this legacy staging entry is not adapted. Use the registered-source import workflow.')
    logging.getLogger("uvicorn.error").info(
        "research-stage request work_id=%s payload=%s", work_id,
        json.dumps(body.model_dump(), ensure_ascii=False, sort_keys=True))
    if body.batch_mode not in ("import_only", "new_batch", "existing_batch"):
        raise HTTPException(400, "batch_mode must be 'import_only', 'new_batch' "
                                 "or 'existing_batch'")
    if body.batch_mode == "existing_batch" and not (body.batch_id or "").strip():
        raise HTTPException(400, "batch_id is required when batch_mode='existing_batch'")
    run = _latest_successful_parse(work_id)
    if not run:
        raise HTTPException(
            409, f"work {work_id} has no successful parse with extracted text; "
                 "parse it before staging into research")
    markdown = Path(run["content_md_path"])
    if not markdown.is_file():
        raise HTTPException(409, f"parse markdown missing: {markdown}")
    # Preserve CRLF bytes as characters: evidence offsets address the
    # immutable parse artifact (same rule as prepare_research_pilot).
    text = markdown.read_bytes().decode("utf-8")
    try:
        result = _call(
            _svc().import_source,
            run["sf_source_path"],
            text=text,
            work_id=work_id,
            source_file_id=run["sf_id"],
            parse_run_id=run["id"],
            citation_key=work_id,
        )
    except HTTPException:
        raise
    response = {
        "work_id": work_id,
        "source_id": result["source_id"],
        "snapshot_id": result.get("snapshot_id"),
        "created": result.get("created", True),
        "batch": None,
        "next": ("在研究视图选择批次后生成任务包，或直接调用 "
                 "POST /api/research/batches/{batch_id}/task-package"),
    }
    if body.batch_mode == "new_batch":
        batch_name = (body.batch_name or f"stage: {work_id}").strip()
        request_key = (body.request_key or f"stage-{work_id}").strip()
        batch = _call(
            _svc().plan_batch,
            request_key=request_key,
            name=batch_name,
            source_ids=[result["source_id"]],
            snapshot_ids={result["source_id"]: result["snapshot_id"]},
        )
        response["batch"] = batch
        response["next"] = (f"批次 {batch['batch_id']} 已创建；"
                            "POST /api/research/batches/{batch_id}/task-package 生成 v5 任务包")
    elif body.batch_mode == "existing_batch":
        relay = _call(
            _svc().relay_source_into_batch,
            body.batch_id.strip(),
            result["source_id"],
            snapshot_id=result["snapshot_id"],
            round_name=body.batch_name,
        )
        response["batch"] = relay
        if relay.get("round_created"):
            response["next"] = (
                f"已创建批次 {relay['batch_id']} 作为所选批次的新一轮"
                f"（parent={relay.get('parent_batch_id')}，共 {relay.get('items')} 项，"
                "release 钉定继承）；原批次保持不变。"
                f"POST /api/research/batches/{relay['batch_id']}/task-package 生成 v5 任务包")
        else:
            response["next"] = (
                f"该材料已在批次 {relay['batch_id']} 及其后续轮次中（原因：{relay.get('reason')}），"
                "未重复建轮。")
    logging.getLogger("uvicorn.error").info(
        "research-stage response work_id=%s batch_id=%s parent_batch_id=%s items=%s",
        work_id, (response.get("batch") or {}).get("batch_id"),
        (response.get("batch") or {}).get("parent_batch_id"),
        (response.get("batch") or {}).get("items"))
    return response





class ResumeBody(BaseModel):
    retry_failed: bool = False
    worker_owner: str | None = None
    lease_seconds: int = Field(default=900, ge=1, le=86400)


class RecoverBody(BaseModel):
    older_than_seconds: int = Field(default=900, ge=0, le=604800)
    worker_owner: str | None = None


class HeartbeatBody(BaseModel):
    source_id: str
    worker_owner: str
    lease_seconds: int = Field(default=900, ge=1, le=86400)


class FailureBody(BaseModel):
    source_id: str
    error: str
    worker_owner: str | None = None
    attempt: int | None = None
    manual_action: bool = False
    manual_reason: str | None = None


class SourceRecordSubmit(BaseModel):
    batch_id: str
    source_id: str
    snapshot_id: str
    schema_version: str
    payload: dict[str, Any]
    claims: list[dict[str, Any]]
    supersedes_id: str | None = None
    worker_owner: str | None = None
    attempt: int | None = None
    manual_action: bool = False
    manual_reason: str | None = None
    release_id: str | None = None
    expected_head_id: str | None = None
    feedback_id: str | None = None
    submitted_by: str | None = None
    environment_id: str | None = None
    operation_id: str | None = None


class InterpretationSubmit(BaseModel):
    batch_id: str
    source_record_id: str
    schema_version: str
    ontology_version: str = "autonomy-risk-v1"
    ontology_keys: list[str] = Field(default_factory=list)
    payload: dict[str, Any]
    claims: list[dict[str, Any]]
    supersedes_id: str | None = None
    worker_owner: str | None = None
    attempt: int | None = None
    manual_action: bool = False
    manual_reason: str | None = None
    release_id: str | None = None
    expected_head_id: str | None = None
    feedback_id: str | None = None
    scope: dict[str, Any] | None = None
    submitted_by: str | None = None
    metadata_record_id: str | None = None
    environment_id: str | None = None
    operation_id: str | None = None


class Decision(BaseModel):
    decision: str
    note: str = ""
    proposal_id: str | None = None
    actor_id: str | None = None
    # A7 partial adoption scope (which axes/claims the human decision covers)
    scope: dict[str, Any] | None = None
    operation_id: str | None = None


class OntologyProposal(BaseModel):
    base_version: str = "autonomy-risk-v1"
    proposed_version: str
    changed_keys: list[str]
    payload: dict[str, Any]


class RereviewBody(BaseModel):
    interpretation_ids: list[str]
    relabels: dict[str, dict[str, Any]] = Field(default_factory=dict)


class RecordDraftSave(BaseModel):
    batch_id: str
    expected_revision: int = Field(default=0, ge=0)
    change_kind: str
    display: dict[str, dict[str, Any]]
    ontology_keys: list[str] = Field(default_factory=list)
    notes: str = ""
    review_requests: dict[str, str] = Field(default_factory=dict)


class DraftUndo(BaseModel):
    batch_id: str | None = None
    expected_revision: int = Field(ge=1)


class OntologyDraftSave(BaseModel):
    expected_revision: int = Field(default=0, ge=0)
    concept_id: str
    patch: dict[str, Any]
    change_kind: str
    review_request: str = ""


@router.get("/research/schema")
def schema_status():
    ctx = get_research_context()
    return {"plan": migration_plan(ctx), "verify": verify_schema(ctx),
            "code_root": str(REPO_ROOT),
            "runtime_materials_root": os.environ.get("LITLIB_RUNTIME_MATERIALS_ROOT", str(REPO_ROOT)),
            "environment_id": compute_environment_id(ctx.library_root, ctx.db_path)}


@router.post("/research/sources/import")
def import_source(body: SourceImport):
    return _call(_svc().import_source, **body.model_dump())


@router.get("/research/sources/{key}")
def lookup_source(key: str):
    result = _call(_svc().lookup, key)
    if result is None:
        raise HTTPException(404, key)
    return result


@router.get("/research/sources/{source_id}/text")
def read_source(source_id: str, snapshot_id: str | None = Query(None)):
    return _call(_svc().read_text, source_id, snapshot_id=snapshot_id)


@router.get("/research/search")
def search_sources(q: str, limit: int = Query(50, ge=1, le=200)):
    return {"items": _call(_svc().search, q, limit=limit)}


@router.get("/research/risk-vocab")
def risk_vocab():
    """Distinct risk_phenomena values across current interpretations.

    Feeds the Works-page risk filter (LL-DECOUPLE-20260920 §4.5): counts are
    reported for both the usable-baseline and the candidate reading; an
    absent store returns an empty vocab instead of failing.
    """
    from contextlib import closing

    from ..research_context import get_research_context
    ctx = get_research_context()
    out = {"available": False, "usable": {}, "candidate": {}}
    if not ctx.db_path.is_file():
        return out
    try:
        with closing(ctx.connect(read_only=True)) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "research_interpretations" not in tables:
                return out
            out["available"] = True
            for scope, gate in (
                ("usable", "validity_status='active' AND agent_review_status='approved' "
                           "AND content_state='stable'"),
                ("candidate", "validity_status='active'"),
            ):
                for row in conn.execute(
                        f"""SELECT je.value AS value, COUNT(DISTINCT s.work_id) AS works
                            FROM research_interpretations i
                            JOIN research_sources s ON s.id = i.source_id,
                            json_each(i.payload_json, '$.risk_phenomena') je
                            WHERE i.{gate} GROUP BY je.value ORDER BY works DESC, value"""):
                    out[scope][row["value"]] = row["works"]
    except Exception as error:  # noqa: BLE001 — absence is a valid state
        out["available"] = False
        out["error"] = str(error)
    return out


@router.get("/research/query")
def query_research(batch_id: str, q: str | None = None, source_id: str | None = None,
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
                   limit: int = Query(50, ge=1, le=200)):
    return _call(_svc().query, batch_id=batch_id,q=q,source_id=source_id,work_id=work_id,
                 citation_key=citation_key,validation_status=validation_status,
                 mapping_status=mapping_status,update_object=update_object,research_role=research_role,
                 deployment_condition=deployment_condition,agent_review_status=agent_review_status,
                 human_adoption_status=human_adoption_status,
                 source_validation_status=source_validation_status,
                 source_agent_review_status=source_agent_review_status,
                 source_human_adoption_status=source_human_adoption_status,
                 source_validity_status=source_validity_status,
                 interpretation_validation_status=interpretation_validation_status,
                 interpretation_agent_review_status=interpretation_agent_review_status,
                 interpretation_human_adoption_status=interpretation_human_adoption_status,
                 interpretation_validity_status=interpretation_validity_status,
                 source_content_state=source_content_state,
                 interpretation_content_state=interpretation_content_state,
                 content_state=content_state,limit=limit)


@router.get("/research/works/{work_id}")
def research_work(work_id: str, batch_id: str):
    return _call(_svc().work_view, work_id, batch_id=batch_id)


@router.get("/research/drafts/{work_id}")
def record_draft(work_id: str, batch_id: str):
    return _draft_call('get_record', batch_id, work_id)


@router.put("/research/drafts/{work_id}")
def save_record_draft(work_id: str, body: RecordDraftSave):
    values = body.model_dump()
    batch_id = values.pop("batch_id")
    return _draft_call('save_record', batch_id, work_id, **values)


@router.post("/research/drafts/{work_id}/undo")
def undo_record_draft(work_id: str, body: DraftUndo):
    if not body.batch_id:
        raise HTTPException(400, "batch_id is required")
    return _draft_call('undo_record', body.batch_id, work_id,
                 expected_revision=body.expected_revision)


@router.get("/research/ontology-draft")
def ontology_draft():
    return _draft_call('get_ontology')


@router.put("/research/ontology-draft")
def save_ontology_draft(body: OntologyDraftSave):
    return _draft_call('save_ontology', **body.model_dump())


@router.post("/research/ontology-draft/undo")
def undo_ontology_draft(body: DraftUndo):
    return _draft_call('undo_ontology', expected_revision=body.expected_revision)


@router.post("/research/batches/plan")
def plan_batch(body: BatchPlan):
    return _call(_svc().plan_batch, **body.model_dump())


@router.post("/research/batches/{batch_id}/resume")
def resume_batch(batch_id: str, body: ResumeBody):
    return _call(_svc().resume_batch, batch_id, **body.model_dump())


@router.post("/research/batches/{batch_id}/recover-running")
def recover_running(batch_id: str, body: RecoverBody):
    return _call(_svc().recover_running, batch_id, **body.model_dump())


@router.post("/research/batches/{batch_id}/heartbeat")
def heartbeat(batch_id: str, body: HeartbeatBody):
    return _call(_svc().heartbeat_batch_item, batch_id, **body.model_dump())


@router.post("/research/batches/{batch_id}/fail")
def fail_batch_item(batch_id: str, body: FailureBody):
    values = body.model_dump()
    source_id = values.pop("source_id")
    return _call(_svc().mark_batch_item_failed, batch_id, source_id, **values)


@router.post("/research/batches/{batch_id}/reconcile")
def reconcile_batch(batch_id: str):
    return _call(_svc().reconcile_batch, batch_id)


@router.post("/research/source-records")
def submit_source_record(body: SourceRecordSubmit):
    values = body.model_dump()
    operation_id = values.pop("operation_id")
    digest = _request_digest(values, SourceRecordSubmit)
    return _call(_next().run_with_receipt,
                 operation_id, "submit_source_record",
                 lambda: _call(_svc().submit_source_record, **values),
                 target_id=values.get("source_id"), batch_id=body.batch_id,
                 worker_owner=body.worker_owner, request_digest=digest,
                 request_environment_id=body.environment_id)


@router.post("/research/source-records/{record_id}/agent-review")
def agent_review_source(record_id: str, body: Decision):
    return _call(_svc().agent_review_source, record_id, decision=body.decision,
                 note=body.note, actor_id=body.actor_id)


@router.post("/research/source-records/{record_id}/adopt")
def human_adopt_source(record_id: str, body: Decision):
    return _call(_svc().human_adopt_source, record_id, decision=body.decision,
                 note=body.note, scope=body.scope, actor_id=body.actor_id)


@router.get("/research/source-records/{record_id}/impact")
def source_record_impact(record_id: str):
    return _call(_svc().source_record_impact, record_id)


@router.post("/research/interpretations")
def submit_interpretation(body: InterpretationSubmit):
    values = body.model_dump()
    operation_id = values.pop("operation_id")
    digest = _request_digest(values, InterpretationSubmit)
    return _call(_next().run_with_receipt,
                 operation_id, "submit_interpretation",
                 lambda: _call(_svc().submit_interpretation, **values),
                 target_id=values.get("source_record_id"), batch_id=body.batch_id,
                 worker_owner=body.worker_owner, request_digest=digest,
                 request_environment_id=body.environment_id)


@router.post("/research/interpretations/{interpretation_id}/agent-review")
def agent_review(interpretation_id: str, body: Decision):
    return _call(_svc().agent_review, interpretation_id, decision=body.decision,
                 note=body.note, proposal_id=body.proposal_id, actor_id=body.actor_id)


@router.post("/research/interpretations/{interpretation_id}/adopt")
def human_adopt(interpretation_id: str, body: Decision):
    return _call(_svc().human_adopt, interpretation_id, decision=body.decision,
                 note=body.note, scope=body.scope, actor_id=body.actor_id)


@router.get("/research/evidence")
def evidence(record_id: str | None = None, claim_key: str | None = None):
    return {"items": _call(_svc().evidence, record_id=record_id, claim_key=claim_key)}


@router.get("/research/batches/{batch_id}/effective")
def effective(batch_id: str):
    return {"batch_id": batch_id, "items": _call(_svc().effective_interpretations, batch_id)}


@router.get("/research/batches/{batch_id}/usable")
def usable(batch_id: str):
    return _call(_svc().usable_basis, batch_id)


@router.post("/research/ontology/proposals")
def propose_ontology(body: OntologyProposal):
    return _call(_svc().propose_ontology, **body.model_dump())


@router.post("/research/ontology/proposals/{proposal_id}/impact")
def ontology_impact(proposal_id: str):
    return _call(_svc().ontology_impact, proposal_id)


@router.post("/research/ontology/proposals/{proposal_id}/publish-pilot")
def publish_ontology(proposal_id: str):
    return _call(_svc().publish_ontology_pilot, proposal_id)


@router.post("/research/ontology/proposals/{proposal_id}/rereview")
def rereview(proposal_id: str, body: RereviewBody):
    return _call(_svc().partial_rereview, proposal_id, body.interpretation_ids, relabels=body.relabels)


# ----- contract v5: unified definitions and release bundles -----

class DefinitionCreate(BaseModel):
    layer: str
    version: str
    payload: dict[str, Any]
    parent_version: str | None = None


class ReleasePublish(BaseModel):
    refs: dict[str, list[str]]
    note: str = ""


@router.get("/research/definitions")
def list_definitions(layer: str | None = None):
    return {"items": _call(_definitions().list_definitions, layer)}


def _definitions():
    from ..research_definitions import DefinitionService
    return DefinitionService(get_research_context())


@router.post("/research/definitions")
def create_definition(body: DefinitionCreate):
    return _call(_definitions().create_definition, **body.model_dump())


@router.get("/research/definitions/{layer}/{version}")
def get_definition(layer: str, version: str):
    return _call(_definitions().get_definition, layer, version)


@router.get("/research/releases")
def list_releases():
    return {"items": _call(_definitions().list_releases)}


@router.get("/research/releases/current")
def current_release():
    return _call(_definitions().resolve_release, None)


@router.get("/research/releases/{release_id}")
def get_release(release_id: str):
    return _call(_definitions().get_release, release_id)


@router.post("/research/releases")
def publish_release(body: ReleasePublish):
    return _call(_definitions().publish_release, refs=body.refs, note=body.note)


# ----- contract v5: metadata records, research units, layer-generic review -----

class MetadataSubmit(BaseModel):
    work_id: str
    payload: dict[str, Any]
    supersedes_id: str | None = None
    release_id: str | None = None
    batch_id: str | None = None
    feedback_id: str | None = None
    expected_head_id: str | None = None
    submitted_by: str | None = None
    environment_id: str | None = None
    operation_id: str | None = None


class UnitSubmit(BaseModel):
    batch_id: str
    source_record_id: str
    unit_key: str
    payload: dict[str, Any]
    shared_items: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    extensions: list[dict[str, Any]] = Field(default_factory=list)
    supersedes_id: str | None = None
    release_id: str | None = None
    expected_head_id: str | None = None
    submitted_by: str | None = None
    environment_id: str | None = None
    operation_id: str | None = None


def _request_digest(values: dict, model_cls=None) -> str:
    """B4: canonical digest shared with the CLI.  Both entries normalize
    through the SAME Pydantic model, so omitted optionals and explicit
    defaults produce identical digests (R6: C/D/unit non-None defaults)."""
    from ..research_operations import canonical_request_digest
    return canonical_request_digest(values, model_cls)


@router.get("/research/metadata-records/head")
def metadata_head(work_id: str):
    """当前元数据头（反馈面板定位 RMR 目标；只读，工单工作包 B）。"""
    return _call(_next().metadata_head, work_id=work_id)


@router.post("/research/metadata-records")
def submit_metadata_record(body: MetadataSubmit):
    values = body.model_dump()
    operation_id = values.pop("operation_id")
    digest = _request_digest(values, MetadataSubmit)
    return _call(_next().run_with_receipt,
                 operation_id, "submit_metadata_record",
                 lambda: _call(_next().submit_metadata_record, **values),
                 target_id=body.work_id, batch_id=body.batch_id,
                 request_digest=digest,
                 request_environment_id=body.environment_id)


@router.post("/research/units")
def submit_unit(body: UnitSubmit):
    values = body.model_dump()
    operation_id = values.pop("operation_id")
    digest = _request_digest(values, UnitSubmit)
    return _call(_next().run_with_receipt,
                 operation_id, "submit_unit",
                 lambda: _call(_next().submit_unit, **values),
                 target_id=body.source_record_id, batch_id=body.batch_id,
                 request_digest=digest,
                 request_environment_id=body.environment_id)


@router.get("/research/units")
def list_units(source_record_id: str, content_state: str | None = None):
    return _call(_next().units_for_record, source_record_id, content_state=content_state)


@router.post("/research/records/{layer}/{record_id}/agent-review")
def review_layer_record(layer: str, record_id: str, body: Decision):
    return _call(_next().review_record, layer, record_id,
                 decision=body.decision, note=body.note, actor_id=body.actor_id)


@router.get("/research/outputs/{output_id}")
def get_output_history(output_id: str):
    """B7(R6): fetch a historical output's fixed inputs by identity."""
    return _call(_next().get_output_history, output_id)


@router.get("/research/metadata-records/{record_id}/impact")
def metadata_impact(record_id: str):
    """U24: local dependency/impact list for one metadata record."""
    return _call(_next().metadata_impact, record_id)


@router.post("/research/records/metadata/{record_id}/propagate")
def propagate_metadata_record(record_id: str):
    """B9: retry catalog propagation for an approved metadata revision."""
    return _call(_next().propagate_metadata_record, record_id)


@router.post("/research/records/{layer}/{record_id}/adopt")
def adopt_layer_record(layer: str, record_id: str, body: Decision):
    return _call(_next().adopt_record, layer, record_id,
                 decision=body.decision, note=body.note,
                 scope=body.scope, actor_id=body.actor_id)


# ----- contract v5: feedback → formal revision closed loop -----

class FeedbackOpen(BaseModel):
    # page_display 层的 target_id 可省略（默认取 work_id）；其余层必填。
    layer: str
    target_id: str | None = None
    explicit_claim: str
    detail: str = ""
    work_id: str | None = None
    batch_id: str | None = None
    target_version: int | None = None


class FeedbackLink(BaseModel):
    formal_revision_id: str


class FeedbackClose(BaseModel):
    outcome: str
    resolution_note: str = ""
    # B2: retained_with_evidence requires machine-checkable evidence (a
    # snapshot-anchored quote); corrected/partially_corrected may attach
    # supplementary evidence but their gate is the verified revision.
    evidence: dict[str, Any] | None = None


@router.post("/research/feedback")
def open_feedback(body: FeedbackOpen):
    return _call(_next().open_feedback, **body.model_dump())


@router.get("/research/feedback")
def list_feedback(work_id: str | None = None, layer: str | None = None,
                  target_id: str | None = None, status: str | None = None):
    return {"items": _call(_next().list_feedback, work_id=work_id, layer=layer,
                           target_id=target_id, status=status)}


@router.post("/research/feedback/{feedback_id}/link")
def link_feedback(feedback_id: str, body: FeedbackLink):
    return _call(_next().link_feedback_revision, feedback_id, body.formal_revision_id)


@router.post("/research/feedback/{feedback_id}/close")
def close_feedback(feedback_id: str, body: FeedbackClose):
    return _call(_next().close_feedback, feedback_id, outcome=body.outcome,
                 resolution_note=body.resolution_note, evidence=body.evidence)


# ----- 解析纠错：登记 → 候选 → 核查 → 采用（工单工作包 E） -----

class ParseCorrectionWrite(BaseModel):
    model_config = {"extra": "forbid"}
    environment_id: str


class ParseCorrectionOpen(ParseCorrectionWrite):
    work_id: str
    source_id: str
    base_snapshot_id: str
    problem: str
    problem_quote: str
    block: str = ""
    suggestion: str = ""
    start_offset: int | None = None
    end_offset: int | None = None
    reported_by: str | None = None


class ParseCorrectionCandidate(ParseCorrectionWrite):
    expected_candidate_version: int
    replacement_text: str
    rationale: str
    submitted_by: str


class ParseCorrectionVerify(ParseCorrectionWrite):
    candidate_version: int
    verdict: str
    verified_by: str
    note: str = ""


@router.post("/research/parse-corrections")
def open_parse_correction(body: ParseCorrectionOpen):
    return _call(_pcorr().open_correction, **body.model_dump())


@router.get("/research/parse-corrections")
def list_parse_corrections(work_id: str | None = None, source_id: str | None = None,
                           status: str | None = None):
    return {"items": _call(_pcorr().list_corrections, work_id=work_id,
                           source_id=source_id, status=status)}


@router.get("/research/parse-corrections/{correction_id}")
def get_parse_correction(correction_id: str):
    return _call(_pcorr().get_correction, correction_id)


@router.get("/research/parse-corrections/{correction_id}/impact")
def parse_correction_impact(correction_id: str):
    return _call(_pcorr().impact, correction_id)


@router.post("/research/parse-corrections/{correction_id}/candidate")
def candidate_parse_correction(correction_id: str, body: ParseCorrectionCandidate):
    return _call(_pcorr().submit_candidate, correction_id, **body.model_dump())


@router.post("/research/parse-corrections/{correction_id}/verify")
def verify_parse_correction(correction_id: str, body: ParseCorrectionVerify):
    return _call(_pcorr().verify_candidate, correction_id, **body.model_dump())


class ParseCorrectionAdopt(ParseCorrectionWrite):
    candidate_version: int


@router.post("/research/parse-corrections/{correction_id}/adopt")
def adopt_parse_correction(correction_id: str, body: ParseCorrectionAdopt):
    return _call(_pcorr().adopt_correction, correction_id, **body.model_dump())


# ----- contract v5: citation graph (candidates → verified cites) -----

class ReferenceAdd(BaseModel):
    citing_work_id: str | None = None
    external_object: dict[str, Any]
    match_status: str = "candidate"
    note: str = ""


class ReferenceMatch(BaseModel):
    work_id: str
    evidence: dict[str, Any]
    note: str = ""


class ReferenceStatus(BaseModel):
    match_status: str
    note: str = ""


class CiteVerify(BaseModel):
    evidence: dict[str, Any]


@router.post("/research/references")
def add_reference(body: ReferenceAdd):
    return _call(_next().add_reference, **body.model_dump())


@router.post("/research/references/{reference_id}/match")
def match_reference(reference_id: str, body: ReferenceMatch):
    return _call(_next().match_reference, reference_id, work_id=body.work_id,
                 evidence=body.evidence, note=body.note)


@router.post("/research/references/{reference_id}/status")
def reference_status(reference_id: str, body: ReferenceStatus):
    return _call(_next().update_reference_status, reference_id,
                 match_status=body.match_status, note=body.note)


@router.post("/research/cites/{citing_work_id}/{reference_id}/verify")
def verify_cite(citing_work_id: str, reference_id: str, body: CiteVerify):
    return _call(_next().verify_cite, citing_work_id, reference_id, evidence=body.evidence)


@router.get("/research/citations")
def citations(work_id: str | None = None, lifecycle: str = "active"):
    return _call(_next().citations_view, work_id, lifecycle=lifecycle)


# ----- contract v5: review cards (20 张概念卡：基线/试点/草稿状态显式分层) -----

@router.get("/research/ontology/review-cards")
def review_cards():
    """Serve the v5 review-card set.

    Cards carry an explicit status (baseline_released / pilot_candidate /
    draft_candidate / navigation_no_id) and their destination; draft and
    pilot cards are never silently presented as settled ontology concepts.
    """
    from ..db import CODE_ROOT
    import json as _json
    from ..research_runtime_assets import asset_path
    path = asset_path('review_cards')
    if not path.exists():
        raise HTTPException(404, "review-cards-v5.json not found")
    return _json.loads(path.read_text(encoding="utf-8"))


@router.get("/research/ontology/composition")
def ontology_composition(release_id: str | None = None):
    """B5: the fixed released composition — release bundle, ontology concepts,
    §13.4 controlled vocabularies.  Same answer for page, CLI and task packages."""
    from ..research_definitions import DefinitionService
    return _call(DefinitionService(get_research_context()).released_composition, release_id)


# ----- contract v5: task packages for external agents -----

class TaskPackageRequest(BaseModel):
    worker_owner: str
    lease_seconds: int = Field(default=900, ge=1, le=86400)
    note: str = ""


@router.post("/research/batches/{batch_id}/task-package")
def task_package(batch_id: str, body: TaskPackageRequest):
    return _call(_next().create_task_package, batch_id, worker_owner=body.worker_owner,
                 lease_seconds=body.lease_seconds, note=body.note)


# ----- contract v5: cross-paper exports -----

@router.get("/research/batches/{batch_id}/export/matrix")
def export_matrix(batch_id: str, scope: str = "usable", format: str = "json"):
    result = _call(_next().interpretation_matrix, batch_id, scope=scope)
    if format == "csv":
        columns = ["work_id", "citation_key", "source_id", "interpretation_id", "version",
                   "ontology_version", "ontology_keys", "mapping_status", "update_object",
                   "research_role", "deployment_condition", "positions", "statement",
                   "content_state", "in_usable_basis"]
        return PlainTextResponse(_next().to_csv(result["rows"], columns), media_type="text/csv")
    return result


@router.get("/research/batches/{batch_id}/export/comparison")
def export_comparison(batch_id: str):
    return _call(_next().comparison, batch_id)


@router.get("/research/export/citations")
def export_citations(batch_id: str | None = None):
    return _call(_next().citations_export, batch_id)


# ----- stable upgrade: work-level A queue (WF-013) -----

class MetadataTaskEnsure(BaseModel):
    work_id: str
    reason: str
    operation_id: str


class MetadataTaskTransition(BaseModel):
    status: str
    reason: str
    actor_id: str


@router.post("/research/metadata-tasks")
def ensure_metadata_task(body: MetadataTaskEnsure):
    return _call(_next().ensure_metadata_task, **body.model_dump())


@router.get("/research/metadata-tasks")
def list_metadata_tasks(status: str | None = None):
    return _call(_next().list_metadata_tasks, status=status)


@router.get("/research/metadata-worklist")
def metadata_worklist():
    """Batch-free Work inventory for Agent-assisted A extraction and review."""
    return _call(_next().metadata_worklist)


@router.get("/research/works/{work_id}/metadata")
def metadata_work_detail(work_id: str):
    return _call(_next().metadata_work_detail, work_id)


@router.post("/research/metadata-tasks/{task_id}/transition")
def transition_metadata_task(task_id: str, body: MetadataTaskTransition):
    return _call(_next().transition_metadata_task, task_id, **body.model_dump())


# ----- stable upgrade: batch-free work profile (PLATFORM-003) + preflight -----

@router.get("/research/works/{work_id}/profile")
def work_research_profile(work_id: str):
    return _call(_next().work_research_profile, work_id)


@router.get("/research/works/{work_id}/preflight")
def preflight_work(work_id: str):
    return _call(_next().preflight_work, work_id)


# ----- stable upgrade: immutable stable re-review (PLATFORM-001) -----

class StableRereview(BaseModel):
    actor_id: str
    event_key: str
    basis: dict[str, Any]
    scope: dict[str, Any] | None = None
    note: str = ""
    decision: str = "approved"


@router.post("/research/records/{layer}/{record_id}/stable-rereview")
def stable_rereview(layer: str, record_id: str, body: StableRereview):
    return _call(_next().append_stable_rereview, layer, record_id, **body.model_dump())


# ----- stable upgrade: formal cross-batch reuse (EXEC-001) -----

class ReuseBind(BaseModel):
    source_id: str
    source_record_id: str
    interpretation_id: str | None = None
    metadata_record_id: str
    reason: str
    operation_id: str
    actor_id: str


@router.get("/research/batches/{batch_id}/preflight-reuse")
def preflight_reuse(batch_id: str, source_id: str):
    return _call(_next().preflight_reuse, batch_id=batch_id, source_id=source_id)


@router.post("/research/batches/{batch_id}/reuse-binding")
def bind_reuse(batch_id: str, body: ReuseBind):
    return _call(_next().bind_reuse, batch_id=batch_id, **body.model_dump())


@router.get("/research/batches/{batch_id}/progress")
def batch_progress(batch_id: str):
    return _call(_next().batch_progress, batch_id)


# ----- stable upgrade: reference lifecycle (PLATFORM-002) -----

class ReferenceCorrect(BaseModel):
    corrections: dict[str, Any]
    reason: str
    actor_id: str
    event_key: str
    basis: dict[str, Any] | None = None


class ReferenceMerge(BaseModel):
    canonical_reference_id: str
    reason: str
    actor_id: str
    event_key: str
    basis: dict[str, Any] | None = None


class ReferenceRetire(BaseModel):
    reason: str
    actor_id: str
    event_key: str
    basis: dict[str, Any] | None = None


@router.post("/research/references/{reference_id}/correct")
def correct_reference(reference_id: str, body: ReferenceCorrect):
    return _call(_next().correct_reference, reference_id, **body.model_dump())


@router.post("/research/references/{reference_id}/merge")
def merge_reference(reference_id: str, body: ReferenceMerge):
    return _call(_next().merge_references, reference_id, **body.model_dump())


@router.post("/research/references/{reference_id}/retire")
def retire_reference(reference_id: str, body: ReferenceRetire):
    return _call(_next().retire_reference, reference_id, **body.model_dump())


@router.get("/research/references/{reference_id}/history")
def reference_history(reference_id: str):
    return _call(_next().reference_history, reference_id)
