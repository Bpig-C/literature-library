"""Four-layer research definitions and immutable release bundles.

A *definition* is a versioned field/structure contract for one record layer
(metadata, source_record, interpretation, ontology).  A *release bundle* is the
immutable set of one definition version per layer; record submissions bind the
bundle active at submission time.  Released definitions never change in place.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .research_context import REPO_ROOT, ResearchContext


LAYERS = ("metadata", "source_record", "interpretation", "ontology")
BASELINE_ONTOLOGY_PATH = REPO_ROOT / "ontology" / "autonomy-risk-v1.json"

UNIT_FIELDS = (
    "definitions", "setup", "process_constraints", "methods", "conditions", "measures",
    "findings", "author_claims", "author_explanations", "author_limitations",
    "author_open_questions",
)
INTERPRETATION_MINIMAL = ("statement", "scope", "reasoning", "support_boundary")
METADATA_MINIMAL = ("original_title", "authors")

# design-issues §13.4：分类关联受控值。新增正式受控值仍走定义发布，
# 这里只承载当前发布组合的首版值。
CONTROLLED_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "mapping_status": ("mapped", "partially_mapped", "unmapped", "ambiguous"),
    "research_aspects": ("capability", "conditional_behavior", "propensity",
                         "formation_mechanism", "scenario_consequence",
                         "control_condition_or_failure", "method_or_norm"),
    "research_roles": ("measure", "elicit", "explain", "mitigate", "theorize", "govern"),
    "update_intervention.kind": ("parameter", "harness", "mixed", "none", "unclear"),
    "positions.relation": ("formation", "manifestation", "impact", "measure_target"),
    "positions.location": ("parameter_update", "harness_configuration", "runtime_execution",
                           "evaluation_feedback", "deployment_environment", "human_organization"),
}

DEFAULT_DEFINITIONS: dict[str, dict] = {
    "metadata": {
        "definition": "metadata",
        "version": "metadata-v5",
        "summary": "书目/资源层字段结构：完整作者与角色、双编号、类型与日期事件、资源与开放性、扩展条目。",
        "required_minimal": list(METADATA_MINIMAL),
        "fields": {
            "original_title": {"shape": "{text, language}", "rule": "逐字原题；译名另存于 title_translations"},
            "title_translations": {"shape": "[{text, language}]", "rule": "展示用途，独立版本化，不替代原题"},
            "authors": {"shape": "[{display_name, party_roles[]}] (完整有序列表)",
                        "rule": "页面可缩略，存储与导出必须完整有序"},
            "party_roles": {"shape": "[author|institution|publisher|chair|translator|contact]",
                            "rule": "逐条目标注角色；主席/机构署名不得并入作者名"},
            "doi": {"shape": "string|null", "rule": "与 arXiv 编号分开保存；版本归属由 date_events/版本绑定决定"},
            "arxiv": {"shape": "string|null", "rule": "预印本编号；与正式版关联用 related_versions"},
            "document_type": {"shape": "string", "rule": "不由网页域名直接推断"},
            "language": {"shape": "string", "rule": "文献本体语言"},
            "date_events": {"shape": "[{event, date, precision, bound_version}]",
                            "rule": "按事件记录日期并绑定所引版本；不伪造月日"},
            "citation_year": {"shape": "string", "rule": "引用年，绑定所引版本"},
            "original_abstracts": {"shape": "[{text, language, bound_version}]", "rule": "原始摘要逐字保留"},
            "abstract_translations": {"shape": "[{text, language, bound_version}]",
                                      "rule": "摘要翻译独立版本化，不冒充原文"},
            "descriptive_overview": {"shape": "string", "rule": "Agent 撰写，默认中文"},
            "related_versions": {"shape": "[{relation, work_id?, doi?, arxiv?}]",
                                 "rule": "预印本与正式发表版本的可追溯关联"},
            "resources": {"shape": "[{kind, url, openness, components, conditions}]",
                          "rule": "开源信息明确对象/组件/条件；API 可用不等于组件开源"},
            "resource_observations": {"shape": "[{source_nature, time_scope, checked_at, components, conditions, openness_overview}]",
                                      "rule": "资源现状核查记录；当前状态不覆盖历史声明"},
            "supports": {"shape": "[{claim, evidence_refs[]}]", "rule": "有证据支撑的字段说明"},
            "missing_notes": {"shape": "[string]", "rule": "显式缺失/未报告说明；未报告不等于未实施"},
            "extensions": {"shape": "[{name, content, source, scope, needs_verification}]",
                           "rule": "具名扩展；不覆盖正式字段，不形成并列权威值"},
        },
        "extensions_rule": "三层共用扩展规则：保留名称/内容/来源/范围/待查状态，按所属层核查。",
    },
    "source_record": {
        "definition": "source_record",
        "version": "source-record-v5.1",
        "parent_version": "source-record-v5",
        "summary": "原文遵循层：研究单元、同篇共享设定、缺口与扩展；条件含概念判据与过程约束。"
                   "v5.1：显式 record_mode 支持 background/not_applicable，缺披露路径不再强编单元。",
        "record_fields": {
            "shared_items": {"rule": "同篇共享设定（背景/判据/对照），单元可复用"},
            "gaps": {"rule": "抽取缺口与未核查事项，与作者局限分开"},
            "extensions": {"rule": "具名扩展，保留来源/范围/待查状态"},
            "units": {"rule": "多实验分单元；同篇不同操作化判据分别保存并绑定单元"},
            "record_mode": {"rule": "units（默认，研究内容）| background（背景材料，不强编单元）| "
                                    "not_applicable（与本图谱无关/缺披露）；非 units 必须显式声明并给依据"},
        },
        "unit_required_minimal": ["definitions"],
        "unit_fields": {
            name: {"rule": rule}
            for name, rule in {
                "definitions": "作者概念定义/操作化判据，逐字或忠实转述",
                "setup": "背景设定；FSM 等过程约束归 process_constraints",
                "process_constraints": "FSM 转移规则等过程约束；不是所有 FSM 都当背景",
                "methods": "作者方法描述",
                "conditions": "完整适用条件：场景/环境/概念判据；不同单元不串用",
                "measures": "度量与指标",
                "findings": "作者报告的结果，含支持与不支持的方向",
                "author_claims": "作者明确主张",
                "author_explanations": "作者解释（与作者主张分开）",
                "author_limitations": "作者自述局限；Agent 批评不得写入此处",
                "author_open_questions": "作者留下的开放问题",
            }.items()
        },
        "extensions_rule": "同上；单元差异明确，不强行统一判据。",
    },
    "interpretation": {
        "definition": "interpretation",
        "version": "interpretation-v5",
        "summary": "解释层最小命题骨架：statement + scope/input_refs + reasoning + support_boundary；反向证据必须表达。",
        "required_minimal": list(INTERPRETATION_MINIMAL),
        "fields": {
            "statement": {"rule": "一条可复核的命题"},
            "scope": {"rule": "对象与确切输入范围 {input_refs[], work_scope, conditions[]}；范围须与原文单元对应"},
            "reasoning": {"rule": "从证据到命题的推导，默认中文"},
            "support_boundary": {"rule": "支持边界：证据支持到哪里为止；未报告不等于未实施"},
            "counterevidence": {"rule": "反向材料必须表达；不能只选正向结果"},
            "ontology_keys": {"rule": "绑定的本体概念 ID；未映射可留空并记录 mapping_status"},
            "associations": {"rule": "[{research_aspects, research_roles, update_intervention, positions, mapping_status}]；不任意组合"},
            "extensions": {"rule": "具名扩展"},
        },
        "extensions_rule": "同上；待查意见可保存，不得冒充原文事实。",
    },
    "ontology": {
        "definition": "ontology",
        "version": "ontology-ref-v5",
        "summary": "本体层引用定义：指向机器本体版本及其内容哈希。",
        "ontology_version": "autonomy-risk-v1",
        "sha256": None,  # filled at seed time from the baseline ontology file
        "card_count": None,
    },
}


def _sha_text(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _baseline_ontology() -> dict:
    from .research_runtime_assets import asset_path
    return json.loads(asset_path('baseline').read_text(encoding='utf-8'))


def baseline_definition_payloads() -> dict[str, dict]:
    """Fresh copies of the v5 seed definitions with the ontology hash bound."""
    payloads = {layer: json.loads(json.dumps(payload, ensure_ascii=False))
                for layer, payload in DEFAULT_DEFINITIONS.items()}
    ontology = _baseline_ontology()
    payloads["ontology"]["sha256"] = _sha_text(ontology)
    payloads["ontology"]["card_count"] = len(ontology.get("concepts", []))
    return payloads


def seed_definitions_and_release(conn: sqlite3.Connection, *, contract_version: int, now: str) -> dict:
    """Idempotently insert the v5 baseline definitions and their release bundle."""
    payloads = baseline_definition_payloads()
    refs = []
    for layer in LAYERS:
        payload = payloads[layer]
        version = payload["version"]
        existing = conn.execute(
            "SELECT id,sha256,status,parent_version FROM research_definitions WHERE layer=? AND version=?",
            (layer, version),
        ).fetchone()
        sha = _sha_text(payload)
        if existing is None:
            definition_id = f"RDF-{sha[:16]}"
            conn.execute(
                """INSERT INTO research_definitions
                   (id,layer,version,sha256,payload_json,status,parent_version,created_at)
                   VALUES (?,?,?,?,?,'released',?,?)""",
                (definition_id, layer, version, sha, json.dumps(payload, ensure_ascii=False),
                 payload.get("parent_version"), now),
            )
        else:
            definition_id = existing["id"]
            if existing["sha256"] != sha:
                raise RuntimeError(
                    f"baseline definition {layer}@{version} already exists with different content"
                )
        refs.append({"layer": layer, "definition": definition_id, "version": version, "sha256": sha})
    release_id = "RDR-" + _sha_text({"contract_version": contract_version, "refs": refs})[:16]
    existing_release = conn.execute(
        "SELECT id FROM research_definition_releases WHERE id=?", (release_id,)
    ).fetchone()
    if existing_release is None:
        conn.execute(
            """INSERT INTO research_definition_releases
               (id,contract_version,definition_refs_json,note,released_at) VALUES (?,?,?,?,?)""",
            (release_id, contract_version, json.dumps(refs, ensure_ascii=False),
             "v5 整版基线发布包（随结构升级种子化）", now),
        )
    return {"release_id": release_id, "definition_refs": refs}


class DefinitionConflictError(ValueError):
    """A definition version was reused for different content, or a release is invalid."""


class DefinitionService:
    """Read/write access to definitions and release bundles."""

    def __init__(self, context: ResearchContext):
        self.context = context

    def _write_conn(self) -> sqlite3.Connection:
        self.context.require_writable()
        from .research_schema import verify_schema
        if not verify_schema(self.context)["ok"]:
            raise RuntimeError("research schema is not initialized; run migration apply explicitly")
        return self.context.connect()

    def create_definition(self, *, layer: str, version: str, payload: dict,
                          parent_version: str | None = None) -> dict:
        if layer not in LAYERS:
            raise ValueError(f"unknown definition layer: {layer}")
        if not version or not isinstance(payload, dict):
            raise ValueError("definition version and payload object are required")
        payload = json.loads(json.dumps(payload, ensure_ascii=False))
        payload.setdefault("definition", layer)
        payload.setdefault("version", version)
        if payload["version"] != version:
            raise ValueError("payload version does not match definition version")
        sha = _sha_text(payload)
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id,sha256,status FROM research_definitions WHERE layer=? AND version=?",
                (layer, version),
            ).fetchone()
            if existing:
                if existing["sha256"] != sha:
                    raise DefinitionConflictError(
                        f"definition {layer}@{version} already binds different content"
                    )
                conn.commit()
                return {"definition_id": existing["id"], "layer": layer, "version": version,
                        "sha256": sha, "status": existing["status"], "created": False}
            if parent_version and not conn.execute(
                "SELECT 1 FROM research_definitions WHERE layer=? AND version=?", (layer, parent_version)
            ).fetchone():
                raise KeyError(f"parent definition {layer}@{parent_version} not found")
            definition_id = f"RDF-{sha[:16]}"
            conn.execute(
                """INSERT INTO research_definitions
                   (id,layer,version,sha256,payload_json,status,parent_version,created_at)
                   VALUES (?,?,?,?,?,'draft',?,?)""",
                (definition_id, layer, version, sha, json.dumps(payload, ensure_ascii=False),
                 parent_version, _now()),
            )
            conn.commit()
            return {"definition_id": definition_id, "layer": layer, "version": version,
                    "sha256": sha, "status": "draft", "created": True}

    def list_definitions(self, layer: str | None = None) -> list[dict]:
        with closing(self.context.connect(read_only=True)) as conn:
            if layer:
                rows = conn.execute(
                    "SELECT * FROM research_definitions WHERE layer=? ORDER BY created_at", (layer,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_definitions ORDER BY layer,created_at"
                ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json"))
                result.append(item)
            return result

    def get_definition(self, layer: str, version: str) -> dict:
        with closing(self.context.connect(read_only=True)) as conn:
            row = conn.execute(
                "SELECT * FROM research_definitions WHERE layer=? AND version=?", (layer, version)
            ).fetchone()
            if not row:
                raise KeyError(f"{layer}@{version}")
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            return item

    def publish_release(self, *, refs: dict[str, tuple[str, str]] | dict[str, list],
                        note: str = "") -> dict:
        """Publish an immutable bundle of one definition version per layer.

        ``refs`` maps layer -> [definition_id, version].  Publishing is
        idempotent for an identical ref set.
        """
        if set(refs) != set(LAYERS):
            raise ValueError(f"release requires exactly one definition per layer: {sorted(LAYERS)}")
        from .research_schema import CONTRACT
        contract_version = int(CONTRACT["version"])
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            resolved = []
            for layer in LAYERS:
                value = refs[layer]
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise ValueError(f"refs[{layer}] must be [definition_id, version]")
                definition_id, version = str(value[0]), str(value[1])
                row = conn.execute(
                    "SELECT id,layer,version,sha256,status FROM research_definitions WHERE id=? AND layer=? AND version=?",
                    (definition_id, layer, version),
                ).fetchone()
                if not row:
                    raise KeyError(f"definition not found: {layer}@{version} ({definition_id})")
                resolved.append({"layer": layer, "definition": row["id"], "version": row["version"],
                                 "sha256": row["sha256"]})
            release_id = "RDR-" + _sha_text({"contract_version": contract_version, "refs": resolved})[:16]
            existing = conn.execute(
                "SELECT id FROM research_definition_releases WHERE id=?", (release_id,)
            ).fetchone()
            if existing:
                conn.commit()
                return {"release_id": release_id, "created": False,
                        "definition_refs": resolved}
            conn.execute(
                """INSERT INTO research_definition_releases
                   (id,contract_version,definition_refs_json,note,released_at) VALUES (?,?,?,?,?)""",
                (release_id, contract_version, json.dumps(resolved, ensure_ascii=False),
                 note, _now()),
            )
            for item in resolved:
                conn.execute(
                    "UPDATE research_definitions SET status='released' WHERE id=? AND status='draft'",
                    (item["definition"],),
                )
            conn.commit()
            return {"release_id": release_id, "created": True, "definition_refs": resolved}

    def list_releases(self) -> list[dict]:
        with closing(self.context.connect(read_only=True)) as conn:
            rows = conn.execute(
                "SELECT * FROM research_definition_releases ORDER BY released_at"
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["definition_refs"] = json.loads(item.pop("definition_refs_json"))
                result.append(item)
            return result

    def get_release(self, release_id: str) -> dict:
        with closing(self.context.connect(read_only=True)) as conn:
            row = conn.execute(
                "SELECT * FROM research_definition_releases WHERE id=?", (release_id,)
            ).fetchone()
            if not row:
                raise KeyError(release_id)
            item = dict(row)
            item["definition_refs"] = json.loads(item.pop("definition_refs_json"))
            return item

    def resolve_release(self, release_id: str | None) -> dict:
        """Explicit release bundle, or the latest released bundle."""
        if release_id:
            return self.get_release(release_id)
        with closing(self.context.connect(read_only=True)) as conn:
            row = conn.execute(
                "SELECT id FROM research_definition_releases ORDER BY released_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if not row:
            raise KeyError("no definition release has been published")
        return self.get_release(row["id"])

    def released_composition(self, release_id: str | None = None) -> dict:
        """The fixed released composition: release bundle + ontology concepts +
        §13.4 controlled vocabularies, in one queryable answer shared by all
        ends (page, CLI, task package)."""
        from .research_schema import CONTRACT
        release = self.resolve_release(release_id)
        ontology_ref = next(r for r in release["definition_refs"] if r["layer"] == "ontology")
        ontology_definition = self.get_definition("ontology", ontology_ref["version"])
        ontology_version = ontology_definition["payload"].get("ontology_version")
        with closing(self.context.connect(read_only=True)) as conn:
            row = conn.execute("SELECT payload_json FROM research_ontology_versions WHERE version=?",
                               (ontology_version,)).fetchone()
        if not row:
            raise KeyError(ontology_version)
        ontology_payload = json.loads(row[0])
        return {
            "release_id": release["id"],
            "released_at": release.get("released_at"),
            "contract_version": int(CONTRACT["version"]),
            "definition_refs": release["definition_refs"],
            "ontology": {
                "version": ontology_version,
                "sha256": ontology_definition["payload"].get("sha256"),
                "concepts": [
                    {"id": c.get("id") or c.get("key"), "label": c.get("label") or c.get("zh"),
                     "definition": c.get("definition"), "parents": c.get("parents") or []}
                    for c in ontology_payload.get("concepts", [])
                    if isinstance(c, dict) and (c.get("id") or c.get("key"))
                ],
            },
            "controlled_vocabularies": self.released_vocabularies(release["id"]),
            "controlled_vocabulary_authority": (
                "contract §13.4 constants as overridden by the released "
                "definitions' controlled_vocabularies sections"),
        }

    def released_vocabularies(self, release_id: str | None = None) -> dict:
        """B5(R6): the vocabularies this release fixes.

        Only EXPLICITLY declared overrides change a vocabulary: walking each
        layer through ``released_vocabularies_for`` (which back-fills every
        constant) used to reset values another layer had already overridden.
        Here each definition contributes exactly the names it declares, later
        layers override earlier ones, and the merged result is the one answer
        every consumer reads.
        """
        release = self.resolve_release(release_id)
        merged = {name: list(values) for name, values in CONTROLLED_VOCABULARIES.items()}
        overridden_by: dict[str, str] = {}
        for ref in release["definition_refs"]:
            definition = self.get_definition(ref["layer"], ref["version"])
            overrides = (definition["payload"] or {}).get("controlled_vocabularies")
            if not isinstance(overrides, dict):
                continue
            # validate declared names only
            released_vocabularies_for({"controlled_vocabularies": overrides})
            for name, values in overrides.items():
                merged[name] = list(values)
                overridden_by[name] = ref["layer"]
        return merged


def _definition_rules(layer: str, definition_payload: dict) -> dict:
    """Merge built-in defaults with the actually bound definition payload.

    Validation must be driven by the released definition content (contract v5),
    so a definition that adds a required field tightens validation without any
    code change; falling back to built-ins only covers absent keys.
    """
    rules = definition_payload or {}
    return {
        "required_minimal": list(rules.get("required_minimal")
                                 or (INTERPRETATION_MINIMAL if layer == "interpretation"
                                     else METADATA_MINIMAL if layer == "metadata" else [])),
        # B5: the bound source-record definition is the authority on which unit
        # fields exist and which of them are minimal; the code-side tuple is
        # only a fallback for definitions that predate the key.
        "unit_fields": set(rules.get("unit_fields") or {}) or set(UNIT_FIELDS),
        "unit_required_minimal": list(rules.get("unit_required_minimal") or ["definitions"]),
    }


LOCATOR_KINDS = ("text_offset", "page", "figure_region", "html_anchor", "markdown_line")


def validate_locator(locator: Any, snapshot: dict | None = None) -> dict:
    """U19 证据回查链：结构化 locator 必须声明 kind 并携带该 kind 所需字段，
    且在绑定快照上可核对（页数、行号、锚点、版本一致）。

    文本偏移是主键，locator 是人可回查的定位链（页码、图表区域坐标、HTML
    锚点、Markdown 行号——非 PDF 材料同等可用）。无法识别的定位一律拒绝，
    不静默展示；无法在快照上核对的定位（未声明页数、锚点不存在、行号越界、
    版本不符）同样拒绝——不可核对不等于可批准。

    ``snapshot``（可选）为绑定的快照投影：content_text / version /
    page_count / page_width / page_height，以及用于对应性核对的 start_offset。
    """
    if not isinstance(locator, dict) or not locator:
        return {}
    kind = str(locator.get("kind") or "").strip()
    if kind not in LOCATOR_KINDS:
        raise ValueError(f"locator.kind must be one of {sorted(LOCATOR_KINDS)}")
    cleaned: dict = {"kind": kind}
    if kind in {"page", "figure_region"}:
        page = locator.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError(f"{kind} locator requires an integer page >= 1")
        cleaned["page"] = page
        if locator.get("page_label"):
            cleaned["page_label"] = str(locator["page_label"])
        page_count = (snapshot or {}).get("page_count")
        if page_count is None:
            raise ValueError(
                f"{kind} locator page {page} cannot be checked: the bound snapshot does not "
                "declare page_count (parse must supply it); an unverifiable page reference "
                "is not approvable evidence")
        if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 1:
            raise ValueError("snapshot page_count must be a positive integer")
        if page > page_count:
            raise ValueError(
                f"{kind} locator page {page} is outside the bound snapshot ({page_count} pages)")
        # U19(R6): 页码-文本对应 —— 显式 start_offset 时引文必须落在该页的
        # 文本范围内（默认按页数均分是对机械解析文本的保守近似；解析提供
        # page_offsets 时精确核对）。
        start_offset = (snapshot or {}).get("start_offset")
        content = str((snapshot or {}).get("content_text") or "")
        page_offsets = (snapshot or {}).get("page_offsets")
        if start_offset is not None and content and                 isinstance(page_offsets, list) and len(page_offsets) == page_count + 1:
            # U19(R6): 解析提供逐页偏移时精确核对页码-文本对应；未提供时不做
            # 均分近似（近似会把合法边界误判为错页——页数与范围校验仍然生效）。
            lo, hi = page_offsets[page - 1], page_offsets[page]
            if not (lo <= start_offset < hi):
                raise ValueError(
                    f"{kind} locator page {page} does not contain the quoted offset "
                    f"{start_offset} (page spans {lo}–{hi})")
    if kind == "figure_region":
        box = []
        for name in ("x0", "y0", "x1", "y1"):
            value = locator.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"figure_region locator requires numeric {name}")
            box.append(float(value))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("figure_region box must satisfy x1>x0 and y1>y0")
        cleaned.update({"x0": box[0], "y0": box[1], "x1": box[2], "y1": box[3]})
        if locator.get("figure_label"):
            cleaned["figure_label"] = str(locator["figure_label"])
        # U19(R6): 区域必须落在**该页实际**几何内。快照可声明逐页尺寸
        # page_sizes=[{width,height,rotated}...]（与 page_count 对齐）；无逐页
        # 声明时整篇 width/height 仅对第一页成立——第二页不同尺寸/旋转的合法
        # 坐标不能被第一页几何硬性拒绝。
        width = (snapshot or {}).get("page_width")
        height = (snapshot or {}).get("page_height")
        page_sizes = (snapshot or {}).get("page_sizes")
        page = cleaned["page"]
        rotated_page = False
        if isinstance(page_sizes, list) and len(page_sizes) >= page:
            size = page_sizes[page - 1]
            if isinstance(size, dict):
                width = size.get("width", width)
                height = size.get("height", height)
                rotated_page = bool(size.get("rotated") or
                                    size.get("rotation") in {90, 270})
        elif page > 1 and (width is not None or height is not None):
            raise ValueError(
                f"figure_region locator page {page} cannot be checked: the snapshot only "
                "declares first-page geometry; provide page_sizes for multi-page materials")
        if width is not None and height is not None:
            fw, fh = float(width), float(height)
            inside_page = (
                0 <= box[0] and box[2] <= fw and 0 <= box[1] and box[3] <= fh
            ) or (rotated_page and (
                # 旋转页接受 PDF 原始坐标系和旋转后的显示坐标系。
                0 <= box[0] and box[2] <= fh and 0 <= box[1] and box[3] <= fw
            ))
            if not inside_page:
                raise ValueError(
                    f"figure_region box {box} is outside the bound page geometry "
                    f"({fw}x{fh} for page {page})")
        elif snapshot is not None:
            raise ValueError(
                "figure_region locator cannot be checked: the bound snapshot does not "
                "declare page geometry (page_width/page_height); an unverifiable region "
                "is not approvable evidence")
    if kind == "html_anchor":
        anchor = str(locator.get("anchor") or "").strip()
        if not anchor:
            raise ValueError("html_anchor locator requires an anchor id")
        cleaned["anchor"] = anchor
        content = str((snapshot or {}).get("content_text") or "")
        if snapshot is not None:
            markers = (f'id="{anchor}"', f"id='{anchor}'", f"](#{anchor})")
            if not any(marker in content for marker in markers):
                raise ValueError(
                    f"html_anchor locator anchor '{anchor}' does not exist in the bound "
                    "snapshot content (anchor ids must be present in the stored material)")
            # U19(R6): 包含关系而非“最近 id”——引文必须落在锚点元素的开闭
            # 区间内（锚点本身或其后代均可）。开闭标签按 id 定位：引文偏移
            # ∈ [元素起点, 闭合终点) 即合法；指向已闭合的兄弟节点（引文在
            # 其闭合之后）拒绝——最近 id 无法证明归属。
            start_offset = (snapshot or {}).get("start_offset")
            if start_offset is not None:
                import re as _re
                spans = []  # (open_pos, close_pos, anchor_id)
                for m in _re.finditer(
                        r'<(\w+)[^>]*\bid=["\']([^"\']+)["\'][^>]*>', content):
                    tag, aid = m.group(1), m.group(2)
                    close = _re.search("</" + tag + r"\s*>", content[m.end():])
                    close_pos = (m.end() + close.start()) if close else len(content)
                    spans.append((m.start(), close_pos, aid))
                for m in _re.finditer(r"\]\(#([^)]+)\)", content):
                    spans.append((m.start(), len(content), m.group(1)))
                containing = [s for s in spans if s[0] <= start_offset < s[1]]
                if containing:
                    ok_ids = {s[2] for s in containing}
                    if anchor not in ok_ids:
                        raise ValueError(
                            f"html_anchor locator '{anchor}' does not enclose the quoted "
                            f"offset; the enclosing anchor(s) are {sorted(ok_ids)}")
                else:
                    raise ValueError(
                        f"html_anchor locator '{anchor}' does not correspond to the "
                        "quoted offset: the quote is not inside any anchored element")
    if kind == "markdown_line":
        line = locator.get("line")
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ValueError("markdown_line locator requires an integer line >= 1")
        cleaned["line"] = line
        if snapshot is not None:
            content = str(snapshot.get("content_text") or "")
            lines = content.splitlines()
            total = max(len(lines), 1)
            if line > total:
                raise ValueError(
                    f"markdown_line locator line {line} is outside the bound snapshot "
                    f"({total} lines)")
            # U19(R5): line correspondence — the quoted offset must fall on the
            # declared line, so pointing the 4th-line quote at line 1 is rejected.
            start_offset = (snapshot or {}).get("start_offset")
            if start_offset is not None:
                line_start = sum(len(l) + 1 for l in lines[:line - 1])
                line_end = line_start + len(lines[line - 1]) if line <= len(lines) else line_start
                if not (line_start <= start_offset <= line_end):
                    raise ValueError(
                        f"markdown_line locator line {line} does not correspond to the "
                        f"quoted offset {start_offset} (line {line} spans "
                        f"{line_start}–{line_end})")
    declared_version = locator.get("source_version")
    if declared_version is not None:
        cleaned["source_version"] = str(declared_version)
        if snapshot is not None and snapshot.get("version") is not None and \
                str(declared_version) != str(snapshot["version"]):
            raise ValueError(
                f"locator source_version {declared_version} does not match the bound "
                f"snapshot version {snapshot['version']}; evidence may not jump materials")
    for optional in ("note",):
        if locator.get(optional):
            cleaned[optional] = str(locator[optional])
    return cleaned


def released_vocabularies_for(definition_payload: dict | None) -> dict:
    """B5: the controlled vocabularies a bound definition actually fixes.

    A definition payload may officially override values per vocabulary name
    via a ``controlled_vocabularies`` section; the merged mapping — contract
    constants overridden by the released definition — is the single authority
    validation and every consumer endpoint read for that submission.  Only
    known vocabulary names can be overridden; introducing unknown names is a
    definition error, not silently ignored.
    """
    vocabularies = {name: list(values) for name, values in CONTROLLED_VOCABULARIES.items()}
    overrides = (definition_payload or {}).get("controlled_vocabularies")
    if overrides is None:
        return vocabularies
    if not isinstance(overrides, dict):
        raise ValueError("definition controlled_vocabularies must be an object")
    for name, values in overrides.items():
        if name not in vocabularies:
            raise ValueError(
                f"definition controlled_vocabularies names an unknown vocabulary '{name}'; "
                f"overridable names: {sorted(vocabularies)}")
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(
                f"definition controlled_vocabularies[{name}] must be a list of strings")
        vocabularies[name] = list(values)
    return vocabularies


def validate_associations(associations, valid_concepts: set[str],
                          vocabularies: dict | None = None) -> None:
    """§13.4 classification-association validation.

    One association asserts that its aspects, roles and positions hold for ALL
    of its scope_refs; partial combinations must be split into separate
    associations (a shape rule here; semantic truth is a review concern).
    ``mapped`` must bind a concept of the fixed released composition plus a
    mapping reason; ``unmapped`` must not fabricate concept ids.
    ``vocabularies`` (B5) defaults to the contract constants and is overridden
    by the bound definition's released values.
    """
    vocab = vocabularies or CONTROLLED_VOCABULARIES
    if associations is None:
        return
    if not isinstance(associations, list) or not all(isinstance(a, dict) for a in associations):
        raise ValueError("associations must be a list of objects")
    for index, assoc in enumerate(associations):
        label = f"associations[{index}]"
        scope_refs = assoc.get("scope_refs") or []
        if not isinstance(scope_refs, list) or not all(
                isinstance(ref, str) and ref.strip() for ref in scope_refs):
            raise ValueError(f"{label}.scope_refs must be a list of record/unit ids")
        for field in ("research_aspects", "research_roles"):
            values = assoc.get(field) or []
            if not isinstance(values, list):
                raise ValueError(f"{label}.{field} must be a list")
            name = "research_aspects" if field == "research_aspects" else "research_roles"
            bad = sorted({str(v) for v in values} - set(vocab.get(name) or []))
            if bad:
                raise ValueError(f"{label}.{field} uses values outside the released vocabulary: {bad}")
        intervention = assoc.get("update_intervention")
        if intervention is not None:
            if not isinstance(intervention, dict):
                raise ValueError(f"{label}.update_intervention must be an object with kind")
            kind = intervention.get("kind")
            if kind is not None and kind not in (vocab.get("update_intervention.kind") or []):
                raise ValueError(f"{label}.update_intervention.kind not in released vocabulary: {kind}")
        positions = assoc.get("positions") or []
        if not isinstance(positions, list):
            raise ValueError(f"{label}.positions must be a list")
        for p_index, position in enumerate(positions):
            if not isinstance(position, dict):
                raise ValueError(f"{label}.positions[{p_index}] must be an object")
            for side, vocab_name in (("relation", "positions.relation"),
                                     ("location", "positions.location")):
                value = position.get(side)
                if value is not None and value not in (vocab.get(vocab_name) or []):
                    raise ValueError(
                        f"{label}.positions[{p_index}].{side} not in released vocabulary: {value}")
        if not (assoc.get("research_aspects") or assoc.get("research_roles") or positions):
            raise ValueError(
                f"{label} must carry at least one aspect, role or position; "
                "blank associations cannot pass as classification")
        mapping_status = assoc.get("mapping_status") or "unmapped"
        if mapping_status not in CONTROLLED_VOCABULARIES["mapping_status"]:
            raise ValueError(f"{label}.mapping_status not in released vocabulary: {mapping_status}")
        concept_id = assoc.get("concept_id")
        candidates = assoc.get("candidate_concepts") or []
        if not isinstance(candidates, list) or not all(isinstance(c, str) and c.strip()
                                                       for c in candidates):
            raise ValueError(f"{label}.candidate_concepts must be a list of concept ids")
        reason = str(assoc.get("mapping_reason") or "").strip()
        if mapping_status == "mapped":
            if not concept_id or concept_id not in valid_concepts:
                raise ValueError(
                    f"{label}: mapping_status=mapped must bind a concept of the fixed released "
                    f"composition (got {concept_id!r})")
            if not reason:
                raise ValueError(f"{label}: mapped requires a mapping_reason")
        elif mapping_status == "partially_mapped":
            if not (concept_id or candidates):
                raise ValueError(f"{label}: partially_mapped must bind the matched part "
                                 "(concept_id or candidate_concepts)")
            if not reason:
                raise ValueError(f"{label}: partially_mapped requires mapping_reason "
                                 "stating the matched and unmatched parts")
        elif mapping_status == "unmapped":
            if concept_id:
                raise ValueError(f"{label}: unmapped must not carry a concept_id "
                                 "(do not fabricate ids to pass format checks)")
            if not reason:
                raise ValueError(f"{label}: unmapped retains the queried definitions and "
                                 "reason in mapping_reason")
        elif mapping_status == "ambiguous":
            if not candidates:
                raise ValueError(f"{label}: ambiguous keeps candidates in candidate_concepts "
                                 "separate from a settled binding")
            if concept_id:
                raise ValueError(f"{label}: ambiguous must not also fix concept_id; "
                                 "split candidates and settled bindings")


def derive_association_summaries(associations) -> dict:
    """Root summaries derived from associations (§13.4: not parallel writable truths).

    Returns the projections that root-level fields must be consistent with when
    an interpretation carries associations.  Root fields that cannot be derived
    from association content are simply absent from the result.
    """
    if not associations:
        return {}
    concept_keys: set[str] = set()
    kinds: set[str] = set()
    roles: set[str] = set()
    statuses: set[str] = set()
    for assoc in associations:
        if not isinstance(assoc, dict):
            continue
        status = assoc.get("mapping_status") or "unmapped"
        statuses.add(status)
        if status in ("mapped", "partially_mapped") and assoc.get("concept_id"):
            concept_keys.add(str(assoc["concept_id"]))
        intervention = assoc.get("update_intervention") or {}
        if isinstance(intervention, dict) and intervention.get("kind"):
            kinds.add(str(intervention["kind"]))
        roles |= {str(r) for r in assoc.get("research_roles") or []}
    derived: dict = {"ontology_keys": sorted(concept_keys), "research_roles": sorted(roles)}
    if kinds == {"parameter", "harness"}:
        derived["update_object"] = "mixed"
    elif len(kinds) == 1:
        derived["update_object"] = next(iter(kinds))
    # otherwise update_object is not derivable and stays unset — we do not
    # invent a root truth that no association asserts.
    if len(statuses) == 1:
        derived["mapping_status"] = next(iter(statuses))
    return derived


def validate_payload_against_definition(layer: str, payload: dict, definition_payload: dict) -> None:
    """Structural validation of a record payload against its layer definition.

    Raises ``ValueError`` (surfaced as ``incompatible_definition``) when the
    definition-required parts are missing or malformed.  Named extensions never
    fail validation.  The rules come from the bound definition payload itself
    (``required_minimal``), so new definition versions drive new checks.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"{layer} payload must be an object")
    rules = _definition_rules(layer, definition_payload)
    if layer == "interpretation":
        missing = [key for key in rules["required_minimal"]
                   if not str(payload.get(key) or "").strip()]
        if missing:
            raise ValueError(f"interpretation payload misses definition-required parts: {missing}")
        scope = payload.get("scope")
        if not isinstance(scope, dict):
            raise ValueError("interpretation scope must be an object")
        input_refs = scope.get("input_refs")
        if not isinstance(input_refs, list) or not input_refs or \
                not all(isinstance(ref, str) and ref.strip() for ref in input_refs):
            raise ValueError("interpretation scope.input_refs must be a non-empty list of record/unit ids")
    elif layer == "metadata":
        missing = [key for key in rules["required_minimal"] if not payload.get(key)]
        if missing:
            raise ValueError(f"metadata payload misses definition-required fields: {missing}")
        if "original_title" in payload and not str((payload.get("original_title") or {}).get("text") or "").strip():
            raise ValueError("metadata original_title.text is required")
        authors = payload.get("authors")
        if not isinstance(authors, list) or not authors or not all(
                isinstance(a, dict) and str(a.get("display_name") or "").strip() for a in authors):
            raise ValueError("metadata authors must be a non-empty complete ordered list of "
                             "{display_name, party_roles} entries (display abbreviations are view-only)")
        # U24：开放性声明与不可拆的条件/时间/对象绑定。
        declared_resources: dict[str, dict] = {}
        for index, res in enumerate(payload.get("resources") or []):
            if not isinstance(res, dict) or not str(res.get("kind") or "").strip():
                raise ValueError(f"metadata resources[{index}] requires a kind "
                                 "(what object the openness claim is about)")
            if str(res.get("openness") or "").strip() in {"open", "partially_open"}:
                if not (res.get("components") or res.get("conditions")):
                    raise ValueError(
                        f"metadata resources[{index}] claims open/partially_open without "
                        "components/conditions: API 可用不等于组件开源，开放性必须绑定对象/组件/条件")
            res_id = str(res.get("id") or "").strip()
            if res_id:
                if res_id in declared_resources:
                    raise ValueError(f"metadata resources[{index}] repeats id '{res_id}'")
                declared_resources[res_id] = res
        seen_observations: set[tuple[str, str]] = set()
        for index, obs in enumerate(payload.get("resource_observations") or []):
            if not isinstance(obs, dict):
                raise ValueError(f"metadata resource_observations[{index}] must be an object")
            if not str(obs.get("checked_at") or "").strip():
                raise ValueError(
                    f"metadata resource_observations[{index}] misses checked_at: "
                    "现状核查必须绑定核查时间，时间不可与声明拆分")
            if not str(obs.get("source_nature") or "").strip():
                raise ValueError(f"metadata resource_observations[{index}] misses source_nature")
            # U24：观察必须绑定明确的资源对象与其版本——只有时间/来源标签
            # 而无对象绑定的"现状"不可核验，不得进入 stable。
            obs_target = str(obs.get("resource_id") or "").strip()
            if not obs_target:
                raise ValueError(
                    f"metadata resource_observations[{index}] misses resource_id: "
                    "现状核查必须绑定所观察的资源对象，不能脱离对象只报时间/来源")
            bound = declared_resources.get(obs_target)
            if bound is None:
                raise ValueError(
                    f"metadata resource_observations[{index}] binds unknown resource_id "
                    f"'{obs_target}'; observations may only reference resources declared "
                    "in the same payload")
            obs_version = str(obs.get("version") or "").strip()
            bound_version = str(bound.get("version") or "").strip()
            if not obs_version or not bound_version:
                raise ValueError(
                    f"metadata resource_observations[{index}] must pin the observed version "
                    "and the bound resource must declare its version: 开放状况随版本变化，"
                    "观察不能脱离版本")
            if obs_version != bound_version:
                raise ValueError(
                    f"metadata resource_observations[{index}] pins version {obs_version} but "
                    f"resource '{obs_target}' declares {bound_version}; an observation cannot "
                    "reference a version the resource does not declare")
            key = (str(obs.get("source_nature")), str(obs.get("checked_at")), obs_target)
            if key in seen_observations:
                raise ValueError(
                    f"metadata resource_observations[{index}] repeats the same source_nature "
                    "for the same resource at the same checked_at: 重复权威类型；观察是追加式"
                    "历史，不得相互覆盖")
            seen_observations.add(key)
    elif layer == "source_record":
        mode = str(payload.get("record_mode") or "units")
        if mode not in {"units", "background", "not_applicable"}:
            raise ValueError(f"unknown source_record record_mode: {mode}")
        units = payload.get("units")
        if mode == "units":
            if not isinstance(units, list) or not units:
                raise ValueError("source_record payload requires at least one research unit "
                                 "(or an explicit record_mode: background/not_applicable)")
            for unit in units:
                if not isinstance(unit, dict) or not str(unit.get("unit_key") or "").strip():
                    raise ValueError("every research unit requires a unit_key")
                unknown = sorted(set(unit) - rules["unit_fields"] - {"unit_key", "evidence", "extensions"})
                if unknown:
                    raise ValueError(f"unknown unit fields: {unknown}")
                missing_minimal = [key for key in rules["unit_required_minimal"]
                                   if not str(unit.get(key) or "").strip()]
                if missing_minimal:
                    raise ValueError(f"unit {unit.get('unit_key')} misses definition-required "
                                     f"unit fields (author definitions are the operationalization): "
                                     f"{missing_minimal}")
        else:
            if units:
                raise ValueError(f"record_mode={mode} must not carry units; submit units separately")
            basis = payload.get("background") or payload.get("gaps")
            if not basis:
                raise ValueError(f"record_mode={mode} requires a non-empty background description "
                                 "or explicit gaps list as evidence basis")
    # ontology layer payloads are validated by the machine ontology itself
