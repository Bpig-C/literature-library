"""File-backed editable overlays for the isolated research workflow.

The reviewed records and ontology remain immutable.  This module writes only
under ``<research root>/editing`` and records every save/undo as append-only
JSONL.  Editing is opt-in via ``LITLIB_RESEARCH_EDITING_ENABLED`` and is bound
to the configured research root, so isolated drills never touch pilot/runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .research_context import REPO_ROOT, ResearchContext
from .research_runtime_assets import asset_path
from .research_service import ResearchConflictError, ResearchService


PILOT_RUNTIME_ROOT = (REPO_ROOT / "pilot" / "runtime").resolve()
EDITING_ROOT = PILOT_RUNTIME_ROOT / "editing"
SOURCE_FIELDS = {"conditions", "author_claims", "observations", "limitations", "unresolved"}
INTERPRETATION_FIELDS = {
    "intervention", "observation_access", "formation_or_manifestation", "risk_phenomena",
    "mechanisms", "consequences", "deployment_condition", "reasoning", "assumptions",
    "competing_explanations", "evidence_strength", "classification_issues", "unresolved",
}
ONTOLOGY_FIELDS = {"zh", "definition", "includes", "excludes", "position"}
POSITION_FIELDS = {"formation", "manifestation", "impact", "coverage", "note"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


class ResearchDraftStore:
    def __init__(self, context: ResearchContext):
        self.context = context
        if os.environ.get("LITLIB_RESEARCH_EDITING_ENABLED", "").lower() not in {"1", "true", "yes"}:
            raise PermissionError("pilot draft editing is disabled")
        if context.library_root.resolve() == REPO_ROOT.resolve():
            raise PermissionError("editable drafts must live under an isolated research root")
        self.root = context.library_root / "editing"

    def _paths(self, kind: str, key: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        directory = self.root / kind
        return directory / f"{digest}.json", directory / f"{digest}.history.jsonl"

    @staticmethod
    def _read(path: Path) -> dict | None:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _history(path: Path) -> list[dict]:
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def _write_atomic(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)

    @staticmethod
    def _append(path: Path, event: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _record(self, batch_id: str, work_id: str) -> dict:
        result = ResearchService(self.context).work_view(work_id, batch_id=batch_id)
        items = result.get("items") if isinstance(result, dict) else None
        if not items:
            raise KeyError(work_id)
        return items[0]

    @staticmethod
    def _base_binding(record: dict) -> dict:
        return {
            "source_record_id": record.get("source_record", {}).get("id"),
            "source_record_version": record.get("source_record", {}).get("version"),
            "interpretation_id": record.get("interpretation", {}).get("id"),
            "interpretation_version": record.get("interpretation", {}).get("version"),
            "ontology_version": record.get("interpretation", {}).get("ontology_version"),
        }

    @staticmethod
    def _clean_display(display: dict) -> dict:
        result = {"source": {}, "interpretation": {}}
        for layer, allowed in (("source", SOURCE_FIELDS), ("interpretation", INTERPRETATION_FIELDS)):
            values = display.get(layer) or {}
            if not isinstance(values, dict) or set(values) - allowed:
                raise ValueError(f"unsupported editable {layer} fields")
            result[layer] = _json_copy(values)
        return result

    def get_record(self, batch_id: str, work_id: str) -> dict:
        record = self._record(batch_id, work_id)
        current_path, history_path = self._paths("records", f"{batch_id}\0{work_id}")
        current = self._read(current_path)
        binding = self._base_binding(record)
        binding_matches = not current or current.get("base_binding") == binding or current.get("withdrawn")
        active = bool(current and not current.get("withdrawn") and binding_matches)
        return {
            "active": active,
            "draft": current if active else None,
            "stale_draft": current if current and not current.get("withdrawn") and not binding_matches else None,
            "binding_status": "current" if binding_matches else "stale",
            "revision": int(current.get("revision", 0)) if current else 0,
            "base_binding": binding,
            "history": self._history(history_path),
            "storage": str(current_path),
        }

    def save_record(self, batch_id: str, work_id: str, *, expected_revision: int,
                    change_kind: str, display: dict, ontology_keys: list[str], notes: str,
                    review_requests: dict[str, str]) -> dict:
        if change_kind not in {"wording", "substantive"}:
            raise ValueError("change_kind must be wording or substantive")
        record = self._record(batch_id, work_id)
        current_path, history_path = self._paths("records", f"{batch_id}\0{work_id}")
        before = self._read(current_path)
        current_revision = int(before.get("revision", 0)) if before else 0
        if expected_revision != current_revision:
            raise ResearchConflictError("draft revision changed; reload before saving")
        if before and not before.get("withdrawn") and before.get("base_binding") != self._base_binding(record):
            raise ResearchConflictError("base record revision changed; stale draft cannot be applied silently")
        allowed_keys = self._ontology_ids()
        keys = list(dict.fromkeys(str(key) for key in ontology_keys))
        if set(keys) - allowed_keys:
            raise ValueError("ontology_keys contains an unknown concept")
        requests = {str(key): str(value).strip() for key, value in (review_requests or {}).items() if str(value).strip()}
        revision = current_revision + 1
        original_keys = list(record.get("interpretation", {}).get("ontology_keys") or [])
        baseline = json.loads(asset_path('baseline').read_text(encoding='utf-8'))
        version_ids = {str(item["id"]) for item in baseline["concepts"]} if record.get("interpretation", {}).get("ontology_version") == "autonomy-risk-v1" else allowed_keys
        proposed_keys = sorted(set(keys) - version_ids)
        classification_changed = set(keys) != set(original_keys)
        substantive = change_kind == "substantive" or classification_changed
        after = {
            "kind": "record", "batch_id": batch_id, "work_id": work_id,
            "revision": revision, "saved_at": _now(), "base_binding": self._base_binding(record),
            "change_kind": "substantive" if substantive else "wording",
            "classification_changed": classification_changed,
            "needs_agent_review": substantive or bool(requests),
            "review_status": "pending" if substantive or requests else "not_requested",
            "review_requests": requests, "notes": str(notes),
            "display": self._clean_display(display), "ontology_keys": keys,
            "proposed_ontology_keys": proposed_keys,
            "review_notice": "原 Agent 审阅只针对未改写的原记录，不为当前工作稿背书。",
        }
        self._write_atomic(current_path, after)
        self._append(history_path, {"action": "save", "revision": revision, "at": after["saved_at"], "before": before, "after": after})
        return self.get_record(batch_id, work_id)

    def undo_record(self, batch_id: str, work_id: str, *, expected_revision: int) -> dict:
        self._record(batch_id, work_id)
        current_path, history_path = self._paths("records", f"{batch_id}\0{work_id}")
        before = self._read(current_path)
        if not before or int(before.get("revision", 0)) != expected_revision:
            raise ResearchConflictError("draft revision changed or no draft exists")
        events = self._history(history_path)
        undone = {event.get("target_revision") for event in events if event.get("action") == "undo"}
        last_save = next((event for event in reversed(events) if event.get("action") == "save" and event.get("revision") not in undone), None)
        if not last_save:
            raise ResearchConflictError("last saved revision is unavailable")
        restored = _json_copy(last_save.get("before")) if last_save.get("before") else {
            "kind": "record", "batch_id": batch_id, "work_id": work_id, "withdrawn": True
        }
        restored["revision"] = expected_revision + 1
        restored["saved_at"] = _now()
        self._write_atomic(current_path, restored)
        self._append(history_path, {"action": "undo", "revision": restored["revision"], "target_revision": last_save["revision"], "at": restored["saved_at"], "before": before, "after": restored})
        return self.get_record(batch_id, work_id)

    @staticmethod
    def _ontology_ids() -> set[str]:
        baseline = json.loads(asset_path('baseline').read_text(encoding='utf-8'))
        ids = {str(item["id"]) for item in baseline["concepts"]}
        proposal_path = asset_path('proposal')
        if proposal_path.is_file():
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            ids.update(str(key) for key in proposal.get("changed_keys") or [])
        return ids

    @staticmethod
    def _clean_ontology_patch(concept_id: str, patch: dict) -> dict:
        if concept_id not in ResearchDraftStore._ontology_ids():
            raise KeyError(concept_id)
        if not isinstance(patch, dict) or set(patch) - ONTOLOGY_FIELDS:
            raise ValueError("unsupported ontology draft fields")
        cleaned = _json_copy(patch)
        position = cleaned.get("position")
        if position is not None and (not isinstance(position, dict) or set(position) - POSITION_FIELDS):
            raise ValueError("unsupported ontology position fields")
        return cleaned

    def get_ontology(self) -> dict:
        current_path, history_path = self._paths("ontology", "research-ontology-display")
        current = self._read(current_path)
        base_digest = self._ontology_base_digest()
        binding_matches = not current or current.get("base_digest") == base_digest or current.get("withdrawn")
        active = bool(current and not current.get("withdrawn") and binding_matches)
        return {
            "active": active,
            "draft": current if active else None,
            "stale_draft": current if current and not current.get("withdrawn") and not binding_matches else None,
            "binding_status": "current" if binding_matches else "stale",
            "base_digest": base_digest,
            "revision": int(current.get("revision", 0)) if current else 0,
            "history": self._history(history_path), "storage": str(current_path),
            "precedence": "pilot/runtime/editing ontology overlay > web/src/data/research-ontology-draft.js > machine ontology sources",
        }

    @staticmethod
    def _ontology_base_digest() -> str:
        paths = [
            asset_path('ontology_source'),
            asset_path('baseline'),
            asset_path('proposal'),
        ]
        digest = hashlib.sha256()
        for path in paths:
            if path.is_file():
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def save_ontology(self, *, expected_revision: int, concept_id: str, patch: dict,
                      change_kind: str, review_request: str = "") -> dict:
        if change_kind not in {"wording", "substantive"}:
            raise ValueError("change_kind must be wording or substantive")
        current_path, history_path = self._paths("ontology", "research-ontology-display")
        before = self._read(current_path)
        current_revision = int(before.get("revision", 0)) if before else 0
        if expected_revision != current_revision:
            raise ResearchConflictError("ontology draft revision changed; reload before saving")
        base_digest = self._ontology_base_digest()
        if before and not before.get("withdrawn") and before.get("base_digest") != base_digest:
            raise ResearchConflictError("ontology base changed; stale draft cannot be applied silently")
        overrides = _json_copy((before or {}).get("overrides") or {})
        overrides[concept_id] = self._clean_ontology_patch(concept_id, patch)
        revision = current_revision + 1
        substantive = change_kind == "substantive"
        needs_review = substantive or bool(review_request.strip())
        after = {
            "kind": "ontology", "revision": revision, "saved_at": _now(), "base_digest": base_digest,
            "overrides": overrides,
            "last_concept_id": concept_id, "change_kind": "substantive" if substantive else "wording",
            "needs_agent_review": needs_review, "review_status": "pending" if needs_review else "not_requested",
            "review_request": review_request.strip(),
            "review_notice": "工作稿未发布；原词表审阅状态不为覆盖内容背书。",
        }
        self._write_atomic(current_path, after)
        self._append(history_path, {"action": "save", "revision": revision, "at": after["saved_at"], "before": before, "after": after})
        return self.get_ontology()

    def undo_ontology(self, *, expected_revision: int) -> dict:
        current_path, history_path = self._paths("ontology", "research-ontology-display")
        before = self._read(current_path)
        if not before or int(before.get("revision", 0)) != expected_revision:
            raise ResearchConflictError("ontology draft revision changed or no draft exists")
        events = self._history(history_path)
        undone = {event.get("target_revision") for event in events if event.get("action") == "undo"}
        last_save = next((event for event in reversed(events) if event.get("action") == "save" and event.get("revision") not in undone), None)
        if not last_save:
            raise ResearchConflictError("last saved revision is unavailable")
        restored = _json_copy(last_save.get("before")) if last_save.get("before") else {"kind": "ontology", "withdrawn": True}
        restored["revision"] = expected_revision + 1
        restored["saved_at"] = _now()
        self._write_atomic(current_path, restored)
        self._append(history_path, {"action": "undo", "revision": restored["revision"], "target_revision": last_save["revision"], "at": restored["saved_at"], "before": before, "after": restored})
        return self.get_ontology()
