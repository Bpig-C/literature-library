"""Operation-effect journal shared by the v5 research services (contract v5, B4).

A receipt-wrapped operation must be recoverable as a whole: the business
result and the receipt that describes it must not drift apart when a process
dies between the business commit and the receipt finalize.  Services record
their public result into ``research_operation_effects`` inside the *same
transaction* as the business write; ``run_with_receipt`` replays that journal
on retry instead of re-executing, so an interrupted operation can never
produce a second committed business object.
"""
from __future__ import annotations

import json
import sqlite3
import threading

_operation_ctx = threading.local()


def current_operation_id() -> str | None:
    return getattr(_operation_ctx, "operation_id", None)


def set_current_operation(operation_id: str | None) -> None:
    _operation_ctx.operation_id = operation_id


def record_operation_effect(conn: sqlite3.Connection, result: dict) -> None:
    """Persist the operation's business result alongside its writes.

    Called inside the caller's write transaction, before commit.  No-op when
    the code runs outside a receipt-wrapped operation (direct CLI/service use),
    so the journal only ever tracks receipt-bound effects.
    """
    operation_id = current_operation_id()
    if not operation_id:
        return
    seq = conn.execute(
        "SELECT COALESCE(MAX(seq),0)+1 FROM research_operation_effects WHERE operation_id=?",
        (operation_id,),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO research_operation_effects
           (operation_id,seq,result_json,created_at) VALUES (?,?,?,datetime('now'))""",
        (operation_id, seq, json.dumps(result, ensure_ascii=False)),
    )


def committed_effects(conn: sqlite3.Connection, operation_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT seq,result_json FROM research_operation_effects WHERE operation_id=? ORDER BY seq",
        (operation_id,),
    ).fetchall()
    effects = []
    for row in rows:
        try:
            effects.append(json.loads(row["result_json"]))
        except (json.JSONDecodeError, TypeError):
            effects.append({"raw": row["result_json"]})
    return effects

# B4: receipt recovery is only defined for first-party business methods that
# journal their effects in-transaction.  Arbitrary callbacks cannot be
# recovered (a committed non-journaled write is indistinguishable from a
# rolled-back one), so run_with_receipt rejects other task kinds up front
# instead of silently accepting an unsupported recovery protocol.
RECEIPT_RECOVERABLE_KINDS = frozenset({
    "submit_source_record",
    "submit_interpretation",
    "submit_metadata_record",
    "submit_unit",
})


def canonical_request_digest(values: dict, model_cls=None) -> str:
    """B4: one request normalization shared by CLI and HTTP.

    environment_id is bound by the target store (never part of the caller's
    intent).  When ``model_cls`` is given, BOTH entries parse their payload
    through the same Pydantic model first, so omitted optionals and explicit
    defaults normalize identically (R5: C/D/unit non-None defaults used to
    conflict across entries).
    """
    import hashlib
    if model_cls is not None:
        values = model_cls.model_validate(values).model_dump()
    normalized = {k: v for k, v in values.items()
                  if k != "environment_id" and v is not None}
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
