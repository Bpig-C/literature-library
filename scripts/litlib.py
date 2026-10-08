"""CLI adapter over :mod:`api.research_service` and :mod:`api.research_next`;
contains no workflow logic."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.research_context import ResearchContext
from api.research_next import ResearchNextService
from api.research_schema import apply_schema, compute_environment_id, migration_plan, verify_schema
from api.research_definitions import DefinitionService
from api.research_service import ResearchService


def _json_arg(value: str):
    path = Path(value)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else json.loads(value)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="litlib")
    ap.add_argument("--library-root", required=True)
    ap.add_argument("--db-path")
    ap.add_argument("--read-only", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init"); init.add_argument("--apply", action="store_true")
    imp = sub.add_parser("import"); imp.add_argument("source_path"); imp.add_argument("--text", required=True)
    for name in ("work-id","source-file-id","parse-run-id","citation-key","parse-quality"):
        imp.add_argument("--"+name)
    # U19: declare material geometry publicly so locator claims are checkable
    imp.add_argument("--page-count", type=int)
    imp.add_argument("--page-width", type=float)
    imp.add_argument("--page-height", type=float)
    imp.add_argument("--page-sizes", help="JSON array or path: one width/height/rotation object per page")
    imp.add_argument("--page-offsets", help="JSON array or path: page_count+1 text boundaries")
    imp.add_argument("--citation-keys")
    look = sub.add_parser("lookup"); look.add_argument("key")
    read = sub.add_parser("read"); read.add_argument("source_id"); read.add_argument("--snapshot-id")
    sea = sub.add_parser("search"); sea.add_argument("query")
    plan = sub.add_parser("plan"); plan.add_argument("--request-key",required=True); plan.add_argument("--name",required=True); plan.add_argument("--sources",required=True); plan.add_argument("--snapshots"); plan.add_argument("--ontology-version",default="autonomy-risk-v1"); plan.add_argument("--rerun",action="store_true"); plan.add_argument("--targets",help="B6 axis/scope contract JSON, e.g. {\"interpretation\":\"not_applicable\"}"); plan.add_argument("--release-id",help="explicit definition release to pin")
    res = sub.add_parser("resume"); res.add_argument("batch_id"); res.add_argument("--retry-failed",action="store_true"); res.add_argument("--worker-owner"); res.add_argument("--lease-seconds",type=int,default=900)
    rec = sub.add_parser("recover-running"); rec.add_argument("batch_id"); rec.add_argument("--older-than-seconds",type=int,default=900); rec.add_argument("--worker-owner")
    hb = sub.add_parser("heartbeat"); hb.add_argument("batch_id"); hb.add_argument("source_id"); hb.add_argument("--worker-owner",required=True); hb.add_argument("--lease-seconds",type=int,default=900)
    fail = sub.add_parser("fail"); fail.add_argument("batch_id"); fail.add_argument("source_id"); fail.add_argument("--error",required=True); fail.add_argument("--worker-owner"); fail.add_argument("--attempt",type=int); fail.add_argument("--manual-action",action="store_true"); fail.add_argument("--manual-reason")
    reconcile = sub.add_parser("reconcile"); reconcile.add_argument("batch_id")
    sr = sub.add_parser("submit-source"); sr.add_argument("--json",required=True)
    srv = sub.add_parser("source-agent-review"); srv.add_argument("record_id"); srv.add_argument("decision"); srv.add_argument("--note",default=""); srv.add_argument("--actor-id")
    sad = sub.add_parser("source-adopt"); sad.add_argument("record_id"); sad.add_argument("decision"); sad.add_argument("--note",default=""); sad.add_argument("--actor-id"); sad.add_argument("--json",dest="scope_json",help="B6 adoption scope JSON")
    it = sub.add_parser("submit-interpretation"); it.add_argument("--json",required=True)
    rv = sub.add_parser("agent-review"); rv.add_argument("interpretation_id"); rv.add_argument("decision"); rv.add_argument("--note",default=""); rv.add_argument("--proposal-id"); rv.add_argument("--actor-id")
    ad = sub.add_parser("adopt"); ad.add_argument("interpretation_id"); ad.add_argument("decision"); ad.add_argument("--note",default=""); ad.add_argument("--actor-id"); ad.add_argument("--json",dest="scope_json",help="B6 adoption scope JSON")
    ev = sub.add_parser("evidence"); ev.add_argument("--record-id"); ev.add_argument("--claim-key")
    qu = sub.add_parser("query"); qu.add_argument("--batch-id",required=True); qu.add_argument("--q")
    for name in ("source-id","work-id","citation-key","validation-status","mapping-status",
                 "update-object","research-role","deployment-condition","agent-review-status",
                 "human-adoption-status","source-validation-status","source-agent-review-status",
                 "source-human-adoption-status","source-validity-status",
                 "interpretation-validation-status","interpretation-agent-review-status",
                 "interpretation-human-adoption-status","interpretation-validity-status"):
        qu.add_argument("--"+name)
    op = sub.add_parser("ontology-propose"); op.add_argument("--json",required=True)
    oi = sub.add_parser("ontology-impact"); oi.add_argument("proposal_id")
    pub = sub.add_parser("ontology-publish"); pub.add_argument("proposal_id")
    rr = sub.add_parser("ontology-rereview"); rr.add_argument("proposal_id"); rr.add_argument("--interpretations",required=True); rr.add_argument("--relabels")
    # ----- contract v5 (ResearchNextService): task packages, units, metadata,
    # feedback, citations and cross-paper exports (controller A10 wiring) -----
    ub = sub.add_parser("usable-basis"); ub.add_argument("batch_id")
    uf = sub.add_parser("units"); uf.add_argument("source_record_id"); uf.add_argument("--content-state")
    su = sub.add_parser("submit-unit"); su.add_argument("--json", required=True)
    tp = sub.add_parser("task-package"); tp.add_argument("batch_id"); tp.add_argument("--worker-owner", required=True); tp.add_argument("--lease-seconds", type=int, default=900); tp.add_argument("--note", default="")
    ve = sub.add_parser("verify-environment"); ve.add_argument("environment_id")
    sm = sub.add_parser("submit-metadata"); sm.add_argument("--json", required=True)
    ra = sub.add_parser("record-adopt"); ra.add_argument("layer"); ra.add_argument("record_id"); ra.add_argument("decision"); ra.add_argument("--note", default=""); ra.add_argument("--actor-id"); ra.add_argument("--json", dest="scope_json", help="B6 adoption scope JSON")
    mr = sub.add_parser("record-review"); mr.add_argument("layer"); mr.add_argument("record_id"); mr.add_argument("decision"); mr.add_argument("--note", default=""); mr.add_argument("--actor-id")
    fo = sub.add_parser("feedback-open"); fo.add_argument("--layer", required=True); fo.add_argument("--target-id", required=True); fo.add_argument("--claim", required=True); fo.add_argument("--detail", default=""); fo.add_argument("--work-id"); fo.add_argument("--batch-id"); fo.add_argument("--version", type=int)
    fl = sub.add_parser("feedback-link"); fl.add_argument("feedback_id"); fl.add_argument("formal_revision_id")
    fc = sub.add_parser("feedback-close"); fc.add_argument("feedback_id"); fc.add_argument("outcome"); fc.add_argument("--note", default=""); fc.add_argument("--json", dest="evidence_json", help="B2 resolution evidence anchor JSON (required for retained_with_evidence)")
    fls = sub.add_parser("feedback-list")
    for name in ("work-id","layer","target-id","status"):
        fls.add_argument("--"+name)
    ra = sub.add_parser("reference-add"); ra.add_argument("--citing-work", required=True); ra.add_argument("--title", required=True); ra.add_argument("--note", default="")
    rm = sub.add_parser("reference-match"); rm.add_argument("reference_id"); rm.add_argument("work_id"); rm.add_argument("--json", required=True); rm.add_argument("--note", default="")
    rs = sub.add_parser("reference-status"); rs.add_argument("reference_id"); rs.add_argument("status"); rs.add_argument("--note", default="")
    cv = sub.add_parser("cite-verify"); cv.add_argument("citing_work"); cv.add_argument("reference_id"); cv.add_argument("--json", required=True)
    ctv = sub.add_parser("citations-view"); ctv.add_argument("--work-id")
    cte = sub.add_parser("citations-export"); cte.add_argument("--batch-id")
    comp = sub.add_parser("composition"); comp.add_argument("--release-id")
    oh = sub.add_parser("output-history"); oh.add_argument("output_id")
    mx = sub.add_parser("matrix"); mx.add_argument("batch_id"); mx.add_argument("--scope", default="usable")
    cp = sub.add_parser("comparison"); cp.add_argument("batch_id")
    args = ap.parse_args(argv)
    root = Path(args.library_root).resolve(); db = Path(args.db_path).resolve() if args.db_path else root/"research.sqlite"
    ctx = ResearchContext(root,db,args.read_only); svc = ResearchService(ctx)
    nxt = ResearchNextService(ctx)
    env_id = compute_environment_id(root, db)

    def _payload(value: str) -> dict:
        # B1: a task already pinned to environment A must never be silently
        # re-interpreted as a task for store B just because the CLI points
        # there.  An explicit environment_id that disagrees with the selected
        # store is a conflict; only an absent value binds this store's identity.
        data = _json_arg(value)
        supplied = data.pop("environment_id", None)
        if supplied is not None and str(supplied).strip() != env_id:
            raise SystemExit(json.dumps({
                "error": "revision_conflict",
                "message": f"payload binds environment_id={supplied} but this CLI target "
                           f"computes {env_id}; refusing to reinterpret the task for a "
                           "different store (B1). Re-run against the bound environment or "
                           "issue a new task for this one.",
                "payload_environment_id": supplied,
                "target_environment_id": env_id,
            }, ensure_ascii=False))
        data["environment_id"] = env_id
        return data

    def _submit_model(name: str):
        from api.routes import research as _research_routes
        return getattr(_research_routes, name)

    def _receipt_payload(value: str, task_kind: str, runner, *, target_key: str,
                         batch_key: str | None = None, model_cls=None):
        # B4: the CLI executes the same receipt protocol as the HTTP layer —
        # an operation_id in the task JSON claims/recovers/replays through
        # research_task_receipts.  R6: both entries normalize through the same
        # Pydantic model, so omitted optionals and explicit defaults digest
        # identically and the same JSON replays across entries.
        data = _payload(value)
        operation_id = data.pop("operation_id", None)
        from api.research_operations import canonical_request_digest
        digest = canonical_request_digest(data, model_cls)
        return nxt.run_with_receipt(
            operation_id, task_kind, lambda: runner(**data),
            target_id=data.get(target_key), batch_id=data.get(batch_key) if batch_key else None,
            worker_owner=data.get("worker_owner"), request_digest=digest,
            request_environment_id=data.get("environment_id"))
    if args.cmd == "init": result = apply_schema(ctx) if args.apply else migration_plan(ctx)
    elif args.cmd == "import":
        text = Path(args.text).read_bytes().decode("utf-8") if Path(args.text).is_file() else args.text
        result = svc.import_source(args.source_path,text=text,work_id=args.work_id,source_file_id=args.source_file_id,parse_run_id=args.parse_run_id,citation_key=args.citation_key,citation_keys=[x for x in (args.citation_keys or "").split(",") if x],parse_quality=args.parse_quality or "unchecked",page_count=args.page_count,page_width=args.page_width,page_height=args.page_height,page_sizes=_json_arg(args.page_sizes) if args.page_sizes else None,page_offsets=_json_arg(args.page_offsets) if args.page_offsets else None)
    elif args.cmd == "lookup": result = svc.lookup(args.key)
    elif args.cmd == "read": result = svc.read_text(args.source_id,snapshot_id=args.snapshot_id)
    elif args.cmd == "search": result = svc.search(args.query)
    elif args.cmd == "plan": result = svc.plan_batch(request_key=args.request_key,name=args.name,source_ids=[x for x in args.sources.split(",") if x],snapshot_ids=_json_arg(args.snapshots) if args.snapshots else None,ontology_version=args.ontology_version,rerun=args.rerun,targets=_json_arg(args.targets) if args.targets else None,release_id=args.release_id)
    elif args.cmd == "resume": result = svc.resume_batch(args.batch_id,retry_failed=args.retry_failed,worker_owner=args.worker_owner,lease_seconds=args.lease_seconds)
    elif args.cmd == "recover-running": result = svc.recover_running(args.batch_id,older_than_seconds=args.older_than_seconds,worker_owner=args.worker_owner)
    elif args.cmd == "heartbeat": result = svc.heartbeat_batch_item(args.batch_id,args.source_id,worker_owner=args.worker_owner,lease_seconds=args.lease_seconds)
    elif args.cmd == "fail": result = svc.mark_batch_item_failed(args.batch_id,args.source_id,error=args.error,worker_owner=args.worker_owner,attempt=args.attempt,manual_action=args.manual_action,manual_reason=args.manual_reason)
    elif args.cmd == "reconcile": result = svc.reconcile_batch(args.batch_id)
    elif args.cmd == "submit-source": result = _receipt_payload(args.json, "submit_source_record", svc.submit_source_record, target_key="source_id", batch_key="batch_id", model_cls=_submit_model("SourceRecordSubmit"))
    elif args.cmd == "source-agent-review": result = svc.agent_review_source(args.record_id,decision=args.decision,note=args.note,actor_id=args.actor_id)
    elif args.cmd == "source-adopt": result = svc.human_adopt_source(args.record_id,decision=args.decision,note=args.note,actor_id=args.actor_id,scope=_json_arg(args.scope_json) if getattr(args,"scope_json",None) else None)
    elif args.cmd == "submit-interpretation": result = _receipt_payload(args.json, "submit_interpretation", svc.submit_interpretation, target_key="source_record_id", batch_key="batch_id", model_cls=_submit_model("InterpretationSubmit"))
    elif args.cmd == "agent-review": result = svc.agent_review(args.interpretation_id,decision=args.decision,note=args.note,proposal_id=args.proposal_id,actor_id=args.actor_id)
    elif args.cmd == "adopt": result = svc.human_adopt(args.interpretation_id,decision=args.decision,note=args.note,actor_id=args.actor_id,scope=_json_arg(args.scope_json) if getattr(args,"scope_json",None) else None)
    elif args.cmd == "evidence": result = svc.evidence(record_id=args.record_id,claim_key=args.claim_key)
    elif args.cmd == "query": result = svc.query(batch_id=args.batch_id,q=args.q,source_id=args.source_id,
        work_id=args.work_id,citation_key=args.citation_key,validation_status=args.validation_status,
        mapping_status=args.mapping_status,update_object=args.update_object,research_role=args.research_role,
        deployment_condition=args.deployment_condition,agent_review_status=args.agent_review_status,
        human_adoption_status=args.human_adoption_status,
        source_validation_status=args.source_validation_status,
        source_agent_review_status=args.source_agent_review_status,
        source_human_adoption_status=args.source_human_adoption_status,
        source_validity_status=args.source_validity_status,
        interpretation_validation_status=args.interpretation_validation_status,
        interpretation_agent_review_status=args.interpretation_agent_review_status,
        interpretation_human_adoption_status=args.interpretation_human_adoption_status,
        interpretation_validity_status=args.interpretation_validity_status)
    elif args.cmd == "ontology-propose": result = svc.propose_ontology(**_json_arg(args.json))
    elif args.cmd == "ontology-impact": result = svc.ontology_impact(args.proposal_id)
    elif args.cmd == "ontology-publish": result = svc.publish_ontology_pilot(args.proposal_id)
    elif args.cmd == "ontology-rereview": result = svc.partial_rereview(args.proposal_id,[x for x in args.interpretations.split(",") if x],relabels=_json_arg(args.relabels) if args.relabels else None)
    elif args.cmd == "usable-basis": result = svc.usable_basis(args.batch_id)
    elif args.cmd == "composition": result = DefinitionService(ctx).released_composition(args.release_id)
    elif args.cmd == "output-history": result = nxt.get_output_history(args.output_id)
    elif args.cmd == "units": result = nxt.units_for_record(args.source_record_id, content_state=args.content_state)
    elif args.cmd == "submit-unit": result = _receipt_payload(args.json, "submit_unit", nxt.submit_unit, target_key="source_record_id", batch_key="batch_id", model_cls=_submit_model("UnitSubmit"))
    elif args.cmd == "task-package": result = nxt.create_task_package(args.batch_id, worker_owner=args.worker_owner, lease_seconds=args.lease_seconds, note=args.note)
    elif args.cmd == "verify-environment": result = {"environment_id": args.environment_id, "matches": nxt.verify_environment(args.environment_id)}
    elif args.cmd == "submit-metadata": result = _receipt_payload(args.json, "submit_metadata_record", nxt.submit_metadata_record, target_key="work_id", model_cls=_submit_model("MetadataSubmit"))
    elif args.cmd == "record-adopt": result = nxt.adopt_record(args.layer, args.record_id, decision=args.decision, note=args.note, actor_id=args.actor_id, scope=_json_arg(args.scope_json) if getattr(args,"scope_json",None) else None)
    elif args.cmd == "record-review": result = nxt.review_record(args.layer, args.record_id, decision=args.decision, note=args.note, actor_id=args.actor_id)
    elif args.cmd == "feedback-open": result = nxt.open_feedback(layer=args.layer, target_id=args.target_id, explicit_claim=args.claim, detail=args.detail, work_id=args.work_id, batch_id=args.batch_id, target_version=args.version)
    elif args.cmd == "feedback-link": result = nxt.link_feedback_revision(args.feedback_id, args.formal_revision_id)
    elif args.cmd == "feedback-close": result = nxt.close_feedback(args.feedback_id, outcome=args.outcome, resolution_note=args.note, evidence=_json_arg(args.evidence_json) if getattr(args,"evidence_json",None) else None)
    elif args.cmd == "feedback-list": result = nxt.list_feedback(work_id=args.work_id, layer=args.layer, target_id=args.target_id, status=args.status)
    elif args.cmd == "reference-add": result = nxt.add_reference(citing_work_id=args.citing_work, external_object={"title": args.title}, note=args.note)
    elif args.cmd == "reference-match": result = nxt.match_reference(args.reference_id, work_id=args.work_id, evidence=_json_arg(args.json), note=args.note)
    elif args.cmd == "reference-status": result = nxt.update_reference_status(args.reference_id, match_status=args.status, note=args.note)
    elif args.cmd == "cite-verify": result = nxt.verify_cite(args.citing_work, args.reference_id, evidence=_json_arg(args.json))
    elif args.cmd == "citations-view": result = nxt.citations_view(args.work_id)
    elif args.cmd == "citations-export": result = nxt.citations_export(args.batch_id)
    elif args.cmd == "matrix": result = nxt.interpretation_matrix(args.batch_id, scope=args.scope)
    elif args.cmd == "comparison": result = nxt.comparison(args.batch_id)
    else: raise ValueError(f"unhandled command: {args.cmd}")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
