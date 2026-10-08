"""解析原文纠错与版本保全（工单 LL-UX-EVIDENCE-20260914 工作包 E）。

区分“渲染错误”（只修展示，不动快照）与“解析内容错误”（允许在回看原件后
提交解析修正版）。本服务实现可走通的最小流程：

  登记(open) → 候选修正版(candidate) → 独立核查(verified/rejected)
  → 采用(adopted: 生成新快照 RTS vN+1) → 下游经现有 RSR 提交绑定

硬边界：
- 不修改作者原文、不覆盖既有固定快照；采用即新增快照行，旧快照可查。
- 候选必须先钉住唯一定位（登记偏移逐字匹配，或唯一逐字匹配辅助定位）；
  重复/不确定匹配停留在待核查，不随便取第一处。
- 核查者与提交者不得同为一人；未核查不得采用，采用不等于下游已用。
- 新快照锚点不继承：受影响证据的重定位只作为“唯一逐字匹配辅助定位”报告，
  下游重新提交时仍走现有逐字段校验（content[start:end]==quote）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing

from .research_context import ResearchContext
from .research_errors import invalid_payload, not_found_error, revision_conflict
from .research_next import _id, _now
from .research_schema import verify_schema
from .research_service import _require_environment

STATUSES = ("open", "candidate", "verified", "rejected", "adopted", "withdrawn")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_parse_corrections (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    base_snapshot_id TEXT NOT NULL,
    block TEXT NOT NULL DEFAULT '',
    problem TEXT NOT NULL,
    suggestion TEXT NOT NULL DEFAULT '',
    problem_quote TEXT NOT NULL,
    start_offset INTEGER,
    end_offset INTEGER,
    location_status TEXT NOT NULL DEFAULT 'exact',
    status TEXT NOT NULL,
    replacement_text TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    candidate_text TEXT,
    candidate_diff_json TEXT,
    candidate_sha256 TEXT,
    submitted_by TEXT NOT NULL DEFAULT '',
    verified_by TEXT,
    verify_note TEXT NOT NULL DEFAULT '',
    adopted_snapshot_id TEXT,
    relocations_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def ensure_table(context: ResearchContext) -> None:
    """附加式迁移：首次使用时确保表存在（幂等），不触碰其他结构。"""
    with closing(context.connect()) as conn:
        conn.execute(_SCHEMA_SQL)
        conn.commit()


class ParseCorrectionService:
    def __init__(self, context: ResearchContext):
        self.context = context

    def _write_conn(self) -> sqlite3.Connection:
        self.context.require_writable()
        if not verify_schema(self.context)["ok"]:
            raise RuntimeError("research schema is not initialized; run migration apply explicitly")
        conn = self.context.connect()
        conn.execute(_SCHEMA_SQL)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(research_parse_corrections)")}
        if "candidate_version" not in columns:
            conn.execute("ALTER TABLE research_parse_corrections ADD COLUMN candidate_version INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE research_parse_corrections SET candidate_version=1 WHERE candidate_text IS NOT NULL")
        conn.execute("""CREATE TABLE IF NOT EXISTS research_parse_correction_history (
            correction_id TEXT NOT NULL, candidate_version INTEGER NOT NULL,
            event TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.commit()
        return conn

    @staticmethod
    def _archive(conn, row, event):
        conn.execute("INSERT INTO research_parse_correction_history VALUES (?,?,?,?,?)",
                     (row["id"], row["candidate_version"], event,
                      json.dumps(dict(row), ensure_ascii=False), _now()))

    @staticmethod
    def _check_version(row, version):
        if version is None or version != row["candidate_version"]:
            raise revision_conflict("candidate_version 已过期或未提供；请重新读取候选后操作")

    # ----- helpers -----
    @staticmethod
    def _snapshot(conn: sqlite3.Connection, snapshot_id: str):
        return conn.execute(
            "SELECT * FROM research_text_snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["candidate_version"] = item.get("candidate_version", 1 if item.get("candidate_text") is not None else 0)
        item["location_status"] = item.get("location_status") or "exact"
        if item.get("candidate_diff_json"):
            item["candidate_diff"] = json.loads(item.pop("candidate_diff_json"))
        else:
            item.pop("candidate_diff_json", None)
            item["candidate_diff"] = None
        item["relocations"] = json.loads(item.pop("relocations_json") or "null")
        return item

    @staticmethod
    def _resolve_location(content: str, quote: str, start, end) -> tuple[int, int, str]:
        """钉住问题定位：登记偏移须逐字匹配；未登记时唯一逐字匹配可辅助，
        重复或找不到时如实标记，不随便取第一处。"""
        if not quote:
            if start is None or end != start or not 0 <= start <= len(content):
                raise invalid_payload("缺失片段须提供明确插入点 start_offset=end_offset，范围不能越界")
            return start, start, "exact-insertion"
        if start is not None:
            end_value = end if end is not None else start + len(quote)
            if start < 0 or end_value < start or end_value > len(content) or content[start:end_value] != quote:
                raise invalid_payload(
                    "登记偏移与逐字引文不一致：start_offset/end_offset 必须满足 "
                    "content[start:end] == quote（Unicode 码点，含 \\r）")
            return start, end_value, "exact"
        total = content.count(quote)
        if total == 1:
            at = content.find(quote)
            return at, at + len(quote), "unique-assisted"
        if total == 0:
            raise invalid_payload("逐字引文在基础快照中未找到；请回查快照原文后重新登记")
        raise invalid_payload(
            f"逐字引文在基础快照中出现 {total} 处，定位不确定；"
            "请提供 start_offset/end_offset 钉住具体一处，不得默认取第一处")

    # ----- flow -----
    def open_correction(self, *, work_id: str, source_id: str, base_snapshot_id: str,
                        problem: str, problem_quote: str, block: str = "",
                        suggestion: str = "", start_offset: int | None = None,
                        end_offset: int | None = None,
                        reported_by: str | None = None, environment_id: str | None = None) -> dict:
        _require_environment(self.context, environment_id)
        if not problem.strip():
            raise invalid_payload("problem 为必填")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            snap = self._snapshot(conn, base_snapshot_id)
            if not snap or snap["source_id"] != source_id:
                raise not_found_error(f"snapshot {base_snapshot_id} not bound to source {source_id}")
            source = conn.execute("SELECT work_id FROM research_sources WHERE id=?", (source_id,)).fetchone()
            if not source or source["work_id"] != work_id:
                raise invalid_payload("work_id 与 source_id 归属不一致")
            content = snap["content_text"] or ""
            start, end, location_status = self._resolve_location(
                content, problem_quote, start_offset, end_offset)
            now = _now()
            correction_id = _id("RPC")
            conn.execute(
                """INSERT INTO research_parse_corrections
                (id,work_id,source_id,base_snapshot_id,block,problem,suggestion,
                 problem_quote,start_offset,end_offset,location_status,status,
                 submitted_by,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?, 'open', ?,?,?)""",
                (correction_id, work_id, source_id, base_snapshot_id,
                 block.strip(), problem.strip(), suggestion.strip(),
                 problem_quote, start, end, location_status,
                 (reported_by or "").strip(), now, now),
            )
            conn.commit()
        return {"correction_id": correction_id, "status": "open",
                "location_status": location_status,
                "start_offset": start, "end_offset": end}

    def list_corrections(self, *, work_id: str | None = None, source_id: str | None = None,
                         status: str | None = None) -> list[dict]:
        where, params = [], []
        for column, value in (("work_id", work_id), ("source_id", source_id), ("status", status)):
            if value:
                where.append(f"{column}=?")
                params.append(value)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with closing(self.context.connect(read_only=True)) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_parse_corrections'"
            ).fetchone()
            if not exists:
                return []  # 尚未有任何登记：只读库不建表，如实返回空清单
            rows = conn.execute(
                f"SELECT * FROM research_parse_corrections{clause} ORDER BY created_at, id",
                params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_correction(self, correction_id: str) -> dict:
        with closing(self.context.connect(read_only=True)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_parse_corrections'").fetchone():
                raise not_found_error(correction_id)
            row = conn.execute(
                "SELECT * FROM research_parse_corrections WHERE id=?", (correction_id,)
            ).fetchone()
            history = []
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_parse_correction_history'").fetchone():
                history = [dict(r) for r in conn.execute("SELECT * FROM research_parse_correction_history WHERE correction_id=? ORDER BY rowid", (correction_id,))]
        if not row:
            raise not_found_error(correction_id)
        result = self._row_to_dict(row)
        result["candidate_version"] = result.get("candidate_version", 1 if result.get("candidate_text") is not None else 0)
        result["candidate_history"] = history
        return result

    def submit_candidate(self, correction_id: str, *, replacement_text: str,
                         rationale: str, submitted_by: str, expected_candidate_version: int | None = None, environment_id: str | None = None) -> dict:
        _require_environment(self.context, environment_id)
        if not submitted_by.strip() or not rationale.strip():
            raise invalid_payload("replacement_text、rationale、submitted_by 均为必填")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_parse_corrections WHERE id=?", (correction_id,)
            ).fetchone()
            if not row:
                raise not_found_error(correction_id)
            self._check_version(row, expected_candidate_version)
            if row["status"] in {"adopted", "withdrawn"}:
                raise revision_conflict(f"correction {correction_id} already {row['status']}")
            if row["start_offset"] is None:
                raise revision_conflict("定位未钉住（重复/未匹配），不能提交候选修正版")
            snap = self._snapshot(conn, row["base_snapshot_id"])
            content = snap["content_text"] or ""
            start, end = row["start_offset"], row["end_offset"]
            if content[start:end] != row["problem_quote"]:
                raise revision_conflict("基础快照与登记定位不一致，请重新登记")
            if replacement_text == row["problem_quote"]:
                raise invalid_payload("候选与原文相同，无可提交的修改")
            candidate_text = content[:start] + replacement_text + content[end:]
            self._archive(conn, row, "before_candidate_revision")
            version = row["candidate_version"] + 1
            now = _now()
            conn.execute(
                """UPDATE research_parse_corrections SET status='candidate', candidate_version=candidate_version+1,
                replacement_text=?, rationale=?, candidate_text=?, candidate_sha256=?,
                candidate_diff_json=?, submitted_by=?, verified_by=NULL, verify_note='',
                adopted_snapshot_id=NULL, updated_at=? WHERE id=?""",
                (replacement_text, rationale.strip(), candidate_text,
                 hashlib.sha256(candidate_text.encode("utf-8")).hexdigest(),
                 json.dumps({
                     "before": content[max(0, start - 60):start] + "⟨" + row["problem_quote"] + "⟩"
                               + content[end:end + 60],
                     "after": content[max(0, start - 60):start] + "⟨" + replacement_text + "⟩"
                              + content[end:end + 60],
                     "old_span": row["problem_quote"], "new_span": replacement_text,
                     "start_offset": start, "end_offset": end,
                 }, ensure_ascii=False),
                 submitted_by.strip(), now, correction_id),
            )
            conn.commit()
        return {"correction_id": correction_id, "status": "candidate", "candidate_version": version,
                "candidate_sha256": hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()}

    def verify_candidate(self, correction_id: str, *, verdict: str, verified_by: str,
                         note: str = "", candidate_version: int | None = None, environment_id: str | None = None) -> dict:
        _require_environment(self.context, environment_id)
        if not note.strip():
            raise invalid_payload("核查说明 note 必填：记录原件位置、检查内容与依据")
        if verdict not in {"approved", "rejected"}:
            raise invalid_payload("verdict 必须是 approved 或 rejected")
        if not verified_by.strip():
            raise invalid_payload("核查必须记录核查者身份（verified_by）")
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_parse_corrections WHERE id=?", (correction_id,)
            ).fetchone()
            if not row:
                raise not_found_error(correction_id)
            self._check_version(row, candidate_version)
            if row["status"] != "candidate":
                raise revision_conflict(
                    f"correction {correction_id} 状态为 {row['status']}，仅候选版可核查")
            if row["submitted_by"] and row["submitted_by"] == verified_by.strip():
                raise revision_conflict(
                    "核查者与提交者不得为同一人；解析修正版必须独立核对原件")
            self._archive(conn, row, "before_review")
            status = "verified" if verdict == "approved" else "rejected"
            conn.execute(
                "UPDATE research_parse_corrections SET status=?, verified_by=?, verify_note=?, updated_at=? WHERE id=?",
                (status, verified_by.strip(), note.strip(), _now(), correction_id),
            )
            conn.commit()
        return {"correction_id": correction_id, "status": status}

    def adopt_correction(self, correction_id: str, *, candidate_version: int | None = None, environment_id: str | None = None) -> dict:
        """核查通过后采用：生成新快照（vN+1），旧快照不变；并产出受影响
        证据的重定位分析。下游记录的采用由既有 RSR 提交流程另行完成。"""
        _require_environment(self.context, environment_id)
        with closing(self._write_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM research_parse_corrections WHERE id=?", (correction_id,)
            ).fetchone()
            if not row:
                raise not_found_error(correction_id)
            self._check_version(row, candidate_version)
            if row["status"] != "verified":
                raise revision_conflict(
                    f"correction {correction_id} 状态为 {row['status']}；未独立核查不得覆盖正式证据来源")
            if (not (row["verified_by"] or "").strip() or not row["verify_note"].strip()
                    or row["verified_by"] == row["submitted_by"]):
                raise revision_conflict("缺少独立核查身份或原件核查依据；请重新提交候选并核查")
            base = self._snapshot(conn, row["base_snapshot_id"])
            latest = conn.execute(
                """SELECT id, version FROM research_text_snapshots WHERE source_id=?
                   ORDER BY version DESC LIMIT 1""", (row["source_id"],)).fetchone()
            if latest["id"] != row["base_snapshot_id"]:
                raise revision_conflict(
                    f"基础版本已过期：{row['base_snapshot_id']} 不是当前最新快照"
                    f"（最新为 {latest['id']} v{latest['version']}）；请在最新基础上重新登记/候选")
            content = base["content_text"] or ""
            start, end = row["start_offset"], row["end_offset"]
            candidate_text = content[:start] + row["replacement_text"] + content[end:]
            # 双重校验：候选文本与登记内容一致，防止并发改动
            if row["candidate_text"] is not None and row["candidate_text"] != candidate_text:
                raise revision_conflict("候选修正版与当前基础快照不一致，请重新生成候选")
            self._archive(conn, row, "before_adoption")
            new_id = _id("RTS")
            new_version = int(latest["version"]) + 1
            conn.execute(
                """INSERT INTO research_text_snapshots
                (id,source_id,version,source_file_id,parse_run_id,content_text,
                 content_sha256,source_sha256,parse_exists,parse_quality,created_at,
                 page_count,page_width,page_height,page_sizes,page_offsets)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id, row["source_id"], new_version, base["source_file_id"],
                 base["parse_run_id"], candidate_text,
                 hashlib.sha256(candidate_text.encode("utf-8")).hexdigest(),
                 base["source_sha256"], base["parse_exists"], base["parse_quality"],
                 _now(), base["page_count"], base["page_width"], base["page_height"],
                 base["page_sizes"], None),
            )
            relocations = self._analyze_relocations(conn, row, content, candidate_text,
                                                    start, end, new_id, new_version)
            conn.execute(
                """UPDATE research_parse_corrections SET status='adopted',
                adopted_snapshot_id=?, relocations_json=?, updated_at=? WHERE id=?""",
                (new_id, json.dumps(relocations, ensure_ascii=False), _now(), correction_id),
            )
            conn.commit()
        return {"correction_id": correction_id, "status": "adopted",
                "adopted_snapshot_id": new_id, "adopted_snapshot_version": new_version,
                "base_snapshot_id": row["base_snapshot_id"],
                "relocations": relocations, "page_offsets_status": "needs_review",
                "page_offsets_note": "解析文本已修订；未继承旧页码偏移，须重新核查定位"}

    @staticmethod
    def _analyze_relocations(conn: sqlite3.Connection, row: sqlite3.Row, old_text: str,
                             new_text: str, start: int, end: int,
                             new_snapshot_id: str, new_version: int) -> dict:
        """受影响证据重定位分析（唯一逐字匹配辅助定位；不继承旧偏移冒充有效）。

        - 位置在修改段之前的证据：偏移不变且逐字复核通过 → verified-unchanged。
        - 位置在修改段之后：按长度差平移“建议值”，并在新文本上逐字复核；
          复核通过 → verified-shifted；不通过 → unmatched。
        - 与修改段相交：无法自动判断 → needs-review（位置迁移与语义影响区分）。
        - 新文本中引文出现多处的：ambiguous（待核查），不给建议偏移。
        """
        delta = len(row["replacement_text"]) - (end - start)
        items = []
        affected_records: dict[str, list[str]] = {}
        evidence_rows = conn.execute(
            """SELECT c.record_layer, c.record_id, c.claim_key, e.quote,
                      e.start_offset, e.end_offset
               FROM research_evidence e JOIN research_claims c ON c.id=e.claim_id
               WHERE e.snapshot_id=?""", (row["base_snapshot_id"],)).fetchall()
        for ev in evidence_rows:
            quote = ev["quote"]
            s, e = ev["start_offset"], ev["end_offset"]
            entry = {
                "record_layer": ev["record_layer"], "record_id": ev["record_id"],
                "claim_key": ev["claim_key"], "quote": quote,
                "old_start": s, "old_end": e,
                "new_snapshot_id": new_snapshot_id, "new_snapshot_version": new_version,
            }
            if e is None or s is None:
                entry["state"] = "needs-review"
                entry["note"] = "旧锚点缺少偏移，无法自动迁移"
            elif e <= start and new_text[s:e] == quote:
                entry["state"] = "verified-unchanged"
                entry["new_start"], entry["new_end"] = s, e
                entry["note"] = "位于修改段之前，位置不变；已在新快照逐字复核"
            elif s >= end:
                ns, ne = s + delta, e + delta
                if 0 <= ns <= ne <= len(new_text) and new_text[ns:ne] == quote:
                    entry["state"] = "verified-shifted"
                    entry["new_start"], entry["new_end"] = ns, ne
                    entry["note"] = "位于修改段之后，按长度差平移并在新快照逐字复核通过"
                elif new_text.count(quote) > 1:
                    entry["state"] = "ambiguous"
                    entry["note"] = "新快照中该引文出现多处，偏移待核查，不默认取第一处"
                else:
                    entry["state"] = "unmatched"
                    entry["note"] = "按平移复核失败且无唯一匹配，如实待核查"
            else:
                entry["state"] = "needs-review"
                entry["note"] = "证据与修改段相交：位置迁移与语义影响需人工判断，不自动迁移"
            items.append(entry)
            affected_records.setdefault(ev["record_id"], []).append(ev["claim_key"])
        return {
            "modified_span": {"start": start, "end": end},
            "new_snapshot_id": new_snapshot_id,
            "new_snapshot_version": new_version,
            "items": items,
            "affected_records": [
                {"record_id": rid, "claim_keys": sorted(set(keys))}
                for rid, keys in sorted(affected_records.items())
            ],
            "note": "重定位是唯一/可复核匹配的辅助定位；下游采用仍须按现有提交流程"
                    "逐字段重新校验锚点并接受独立审查，本分析不等于下游已采用。",
        }

    def impact(self, correction_id: str) -> dict:
        row = self.get_correction(correction_id)
        return {
            "correction_id": correction_id,
            "status": row["status"],
            "work_id": row["work_id"],
            "source_id": row["source_id"],
            "base_snapshot_id": row["base_snapshot_id"],
            "adopted_snapshot_id": row["adopted_snapshot_id"],
            "relocations": row["relocations"],
            "candidate_diff": row["candidate_diff"],
            "page_offsets_status": "needs_review" if row["adopted_snapshot_id"] else "not_adopted",
            "downstream_note": "下游采用 = 以 adopted_snapshot_id 通过现有 "
                               "POST /research/source-records（supersedes 当前头）重新提交；"
                               "本服务不直接改写任何研究记录头。",
        }
