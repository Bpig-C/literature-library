# collector/topics.py
"""Research collection topics with maturity ladder (collector retrieval layer, Task 2).

Two orthogonal dimensions on a collection_topic:

- map_status (ontology relationship maturity, monotone forward):
      seedling -> proposed -> mapped
  No automatic backward transition in v1 (mapped -> seedling/proposed is forbidden;
  a future explicit reset path may be added). Valid forward edges:
      (seedling, proposed), (proposed, mapped), (seedling, mapped)

- lifecycle (collection activity, orthogonal to map_status):
      active | paused | retired

BOUNDARY (critical): this module NEVER writes the library ontology vocab
(risk_domain etc.). Mapping a topic only records the intent as a JSON blob
(`mapped_tags`) on the collection_topics row itself — the vocab value must
already exist in the methodology documentation. No vocab/classification tables
are created or written here.
"""
from __future__ import annotations
import json, secrets
from datetime import datetime, timezone
from api.db import get_conn
from api.classification_vocab import validate_tag_value

# Only these groups are allowed in mapped_tags (collector boundary: reads vocab, never writes it)
_MAPPED_TAG_GROUPS = {"risk_domain", "reading_lane", "method_tags"}


def _validate_mapped_tags(tags: list[dict]) -> None:
    """Validate mapped_tags against the controlled vocabulary.

    Each tag must be ``{group, value}`` where *group* is in ``_MAPPED_TAG_GROUPS``
    and *value* exists in ``VOCAB[group]``.
    """
    for tag in tags:
        if not isinstance(tag, dict) or "group" not in tag or "value" not in tag:
            raise ValueError(f"invalid mapped_tags entry (must be {{group, value}}): {tag!r}")
        group, value = tag["group"], tag["value"]
        if group not in _MAPPED_TAG_GROUPS:
            raise ValueError(f"invalid mapped_tags group: {group!r} (allowed: {sorted(_MAPPED_TAG_GROUPS)})")
        if not validate_tag_value(group, value):
            raise ValueError(f"invalid mapped_tags: {group}={value!r} is not in vocab")

ALLOWED_MAP = {"seedling", "proposed", "mapped"}
ALLOWED_LIFE = {"active", "paused", "retired"}
# 合法 map_status 前进路径（不允许 mapped -> seedling/proposed 回退；v1 不提供 reset）
FORWARD = {("seedling", "proposed"), ("proposed", "mapped"), ("seedling", "mapped")}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _new_id():
    return "CT-" + secrets.token_hex(4)


def create(*, name, description="", seed_paper_ids=None, explicit_ids=None,
           axis_hint=None, map_status="seedling", lifecycle="active"):
    """Create a collection_topic. Defaults to seedling/active.

    query_def captures the discovery inputs that seed this topic:
      - explicit_ids:   paper IDs the user explicitly handed in
      - seed_paper_ids: paper IDs chosen as seeds (e.g. from a hunch)
    """
    if map_status not in ALLOWED_MAP:
        raise ValueError(f"bad map_status {map_status}")
    if lifecycle not in ALLOWED_LIFE:
        raise ValueError(f"bad lifecycle {lifecycle}")
    qd = {"explicit_ids": explicit_ids or [], "seed_paper_ids": seed_paper_ids or []}
    conn = get_conn()
    try:
        ct = {
            "id": _new_id(), "name": name, "description": description,
            "query_def": qd, "map_status": map_status, "lifecycle": lifecycle,
            "mapped_tags": None, "proposed_note": None, "axis_hint": axis_hint,
            "created_at": _now(), "updated_at": _now(),
        }
        conn.execute(
            """INSERT INTO collection_topics
               (id,name,description,query_def,map_status,lifecycle,mapped_tags,
                proposed_note,axis_hint,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (ct["id"], ct["name"], ct["description"], json.dumps(qd, ensure_ascii=False),
             ct["map_status"], ct["lifecycle"], None, None, ct["axis_hint"],
             ct["created_at"], ct["updated_at"]))
        conn.commit()
        return ct
    finally:
        conn.close()


def get(topic_id):
    """Return the full topic row as a dict (with query_def/mapped_tags parsed), or None."""
    conn = get_conn()
    try:
        cur = conn.execute("SELECT * FROM collection_topics WHERE id=?", (topic_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = dict(zip(cols, row))
        d["query_def"] = json.loads(d["query_def"] or "{}")
        if d.get("mapped_tags"):
            d["mapped_tags"] = json.loads(d["mapped_tags"])
        return d
    finally:
        conn.close()


def transition(topic_id, *, to_map_status=None, to_lifecycle=None,
               mapped_tags=None, proposed_note=None):
    """Transition a topic's map_status and/or lifecycle, recording mapping artifacts.

    Guards:
      - map_status moves only along FORWARD edges (idempotent same-value is a no-op).
      - to_map_status='proposed' requires a non-empty proposed_note (the 4 criteria).
      - to_map_status='mapped'  requires mapped_tags.
      - to_lifecycle (if given) must be in ALLOWED_LIFE.

    Persisted artifacts (proposed_note / mapped_tags) are written whenever supplied,
    independent of map_status, so a topic already at 'mapped' can have its tags
    amended without changing status.
    """
    cur = get(topic_id)
    if cur is None:
        raise KeyError(topic_id)
    if to_map_status and to_map_status != cur["map_status"]:
        if (cur["map_status"], to_map_status) not in FORWARD:
            raise ValueError(
                f"forbidden map_status transition {cur['map_status']}->{to_map_status}")
    if to_map_status == "mapped" and not mapped_tags:
        raise ValueError("mapped requires mapped_tags")
    if to_map_status == "proposed" and not proposed_note:
        raise ValueError("proposed requires proposed_note (the 4 criteria)")
    if to_lifecycle and to_lifecycle not in ALLOWED_LIFE:
        raise ValueError(f"bad lifecycle {to_lifecycle}")
    if mapped_tags is not None:
        if not mapped_tags:
            raise ValueError("mapped_tags must be a non-empty list (or None to skip)")
        _validate_mapped_tags(mapped_tags)
    conn = get_conn()
    try:
        sets, args = [], []
        if to_map_status:
            sets.append("map_status=?"); args.append(to_map_status)
        if to_lifecycle:
            sets.append("lifecycle=?"); args.append(to_lifecycle)
        if mapped_tags is not None:
            sets.append("mapped_tags=?"); args.append(json.dumps(mapped_tags, ensure_ascii=False))
        if proposed_note is not None:
            sets.append("proposed_note=?"); args.append(proposed_note)
        sets.append("updated_at=?"); args.append(_now())
        args.append(topic_id)
        conn.execute(f"UPDATE collection_topics SET {', '.join(sets)} WHERE id=?", args)
        conn.commit()
    finally:
        conn.close()
    return get(topic_id)


def list_topics(*, map_status=None, lifecycle=None):
    """List topics, optionally filtered by map_status and/or lifecycle.

    Additive: returns the full row as a dict (id/name/map_status/lifecycle plus
    description/query_def/mapped_tags/proposed_note/axis_hint). Existing consumers
    that read by key are unaffected. query_def/mapped_tags are parsed from JSON,
    matching `get`.
    """
    conn = get_conn()
    try:
        q = "SELECT * FROM collection_topics WHERE 1=1"
        args = []
        if map_status:
            q += " AND map_status=?"; args.append(map_status)
        if lifecycle:
            q += " AND lifecycle=?"; args.append(lifecycle)
        cur = conn.execute(q, args)
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            d["query_def"] = json.loads(d["query_def"] or "{}")
            if d.get("mapped_tags"):
                d["mapped_tags"] = json.loads(d["mapped_tags"])
            out.append(d)
        return out
    finally:
        conn.close()
