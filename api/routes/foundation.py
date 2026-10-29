"""Additive client foundation endpoints; research contracts remain unchanged."""
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Header, Response, Depends
from pydantic import BaseModel, ConfigDict, Field

from .. import parse_plans
from ..db import get_read_conn
from ..storage.core import StorageError, checked_sha
from ..storage.runtime import configured_registry, configured_service, enabled

def no_cache(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(dependencies=[Depends(no_cache)])


@router.get('/remote/foundation-guide')
def guide():
    from pathlib import Path
    import hashlib
    text = (Path(__file__).resolve().parents[2]/'docs/foundation-client.md').read_text('utf-8')
    return {'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}


@router.post('/parse/plan')
def parse_plan(selection: parse_plans.Selection):
    with closing(get_read_conn()) as conn:
        return parse_plans.preview(conn, selection)


class AcceptPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan: dict
    request_id: str = Field(min_length=1, max_length=200)
    max_items: int = Field(ge=1, le=1000)
    max_submissions: int = Field(ge=0, le=1000)
    max_pages: int | None = Field(default=None, ge=1)


@router.post('/parse/plans')
def accept_plan(body: AcceptPlan):
    if not enabled(): raise StorageError('configuration_error', 'immutable storage required')
    return parse_plans.accept(configured_registry(), **body.model_dump())


@router.get('/parse/plans/{plan_id}')
def plan_status(plan_id: str):
    return parse_plans.status(configured_registry(), plan_id)


@router.post('/parse/plans/{plan_id}/archive')
def archive_plan(plan_id: str):
    if not enabled():raise StorageError('configuration_error','immutable storage required')
    return parse_plans.archive(configured_registry(),plan_id)


@router.post('/parse/plans/{plan_id}/step')
def plan_step(plan_id: str):
    from .parse import _run_parse
    if not enabled(): raise StorageError('configuration_error', 'immutable storage required')
    return parse_plans.step(configured_service(), plan_id, _run_parse)


class AbandonItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    position: int = Field(ge=0)
    reason: str = Field(min_length=1,max_length=500)
    job_id: str | None = None
    force: bool = False


@router.post('/parse/plans/{plan_id}/abandon')
def abandon_item(plan_id: str, body: AbandonItem):
    if not enabled():raise StorageError('configuration_error','immutable storage required')
    if not body.force:raise StorageError('invalid_request','explicit force required after inspection')
    return parse_plans.abandon(configured_service(),plan_id,body.position,body.reason,body.job_id)


class IntakeItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: str = Field(min_length=1, max_length=200)
    sha256: str
    work_id: str | None = None
    request_id: str | None = None
    purpose: str | None = None


class Reconcile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[IntakeItem] = Field(min_length=1, max_length=1000)


@router.post('/intake/reconcile')
def reconcile(body: Reconcile):
    """Exact files + purpose receipts. Missing file is not permission to merge."""
    if len({i.client_id for i in body.items}) != len(body.items):
        raise StorageError('invalid_request', 'duplicate client_id')
    result = []
    with closing(get_read_conn()) as conn:
        conn.execute('BEGIN')
        notes = conn.execute("SELECT 1 FROM sqlite_master WHERE name='ingest_notes'").fetchone()
        for item in body.items:
            checked_sha(item.sha256)
            sources = [dict(r) for r in conn.execute('''SELECT sf.id source_file_id,sf.work_id,sf.status,w.read_status
                FROM source_files sf JOIN works w ON w.id=sf.work_id WHERE sf.content_sha256=? ORDER BY sf.id''', (item.sha256,))]
            known = bool(item.work_id and conn.execute('SELECT 1 FROM works WHERE id=?', (item.work_id,)).fetchone())
            state = 'exact_match' if sources else ('work_exists_file_missing' if known else 'file_missing')
            if sources and item.work_id and not any(s['work_id']==item.work_id for s in sources): state = 'identity_conflict'
            if sources and all(s['status']!='active' or s['read_status'] in ('quarantined','archived') for s in sources): state = 'inactive_match'
            purpose_state = 'not_requested'
            if item.request_id:
                purpose_state = 'history_unavailable' if not notes else 'missing'
                if notes:
                    targets = [s['work_id'] for s in sources] if not item.work_id else [item.work_id]
                    for wid in targets:
                        row = conn.execute('SELECT purpose,source_file_id FROM ingest_notes WHERE request_id=? AND work_id=?', (item.request_id,wid)).fetchone()
                        if row and row['source_file_id'] is not None and not any(
                            s['work_id']==wid and s['source_file_id']==row['source_file_id'] for s in sources
                        ):
                            continue
                        if row:
                            purpose_state = 'confirmed' if item.purpose is None or row[0]==item.purpose else 'conflict'
                            break
            result.append(dict(client_id=item.client_id, sha256=item.sha256, state=state, sources=sources, purpose_state=purpose_state))
    return {'items':result, 'counts':{s:sum(i['state']==s for i in result) for s in sorted({i['state'] for i in result})},
            'scope':'submitted manifest only; not an inventory of client-only/server-only libraries'}


class BackupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=200)


@router.get('/remote/backup-status')
def backup_status():
    from ..backup_jobs import describe
    return describe()


@router.post('/remote/backup-jobs', status_code=202)
def request_backup(body: BackupRequest, x_litlib_backup_token: Annotated[str | None, Header()] = None):
    from ..backup_jobs import authorize, enqueue
    authorize(x_litlib_backup_token)
    return enqueue(body.request_id)


@router.get('/remote/backup-jobs/{job_id}')
def backup_job(job_id: str):
    from ..backup_jobs import get_job
    return get_job(job_id)
