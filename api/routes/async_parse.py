"""Explicit async protocol: 202 acceptance, GET status, fenced control writes."""
from typing import Annotated
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from ..parse_queue import Queue, enabled
from ..storage.authority import configured_authority
from ..storage.runtime import configured_service
from ..storage.core import StorageError
from .foundation import no_cache

router=APIRouter(prefix='/async/parse',dependencies=[Depends(no_cache)])


def queue():
    if not enabled():raise StorageError('configuration_error','async parse worker protocol not enabled')
    return Queue(configured_service(),configured_authority())


class Enqueue(BaseModel):
    model_config=ConfigDict(extra='forbid')
    max_tasks:int|None=Field(default=None,ge=1,le=1000)


@router.post('/plans/{plan_id}/enqueue',status_code=202)
def enqueue(plan_id:str,body:Enqueue):return queue().enqueue(plan_id,body.max_tasks)


@router.get('/plans/{plan_id}')
def plan_status(plan_id:str):return queue().plan_status(plan_id)


@router.get('/tasks/{task_id}')
def task_status(task_id:str):return queue().status(task_id)


@router.get('/batches/{batch_id}')
def batch_status(batch_id:str):return queue().batch_status(batch_id)


@router.get('/scheduler')
def scheduler():return queue().overview()


class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reason:str=Field(min_length=1,max_length=500)
    force:bool=False


class Resolution(Action):
    outcome:str
    task_id:str|None=None


@router.post('/tasks/{task_id}/resolve')
def resolve(task_id:str,body:Resolution):
    if not body.force:raise StorageError('invalid_request','explicit force required')
    return queue().resolve(task_id,body.outcome,body.reason,body.task_id)


@router.post('/tasks/{task_id}/{action}')
def action(task_id:str,action:str,body:Action):
    if action not in ('pause','cancel','resume'):raise StorageError('invalid_request','unknown task action')
    if not body.force:raise StorageError('invalid_request','explicit force required')
    return queue().action(task_id,action,body.reason)


class Maintenance(Action):
    owner:str=Field(min_length=1,max_length=200)


@router.post('/scheduler/{action}')
def maintain(action:str,body:Maintenance,x_litlib_backup_token:Annotated[str|None,Header()]=None):
    if action not in ('drain','snapshot','resume','resume-submissions'):raise StorageError('invalid_request','unknown maintenance action')
    from ..backup_jobs import authorize
    authorize(x_litlib_backup_token)
    if not body.force:raise StorageError('invalid_request','explicit force required')
    q=queue()
    if action=='resume-submissions':
        with q.tx() as conn:
            from ..parse_queue import initialize
            initialize(conn);conn.execute('UPDATE parse_queue_control SET submit_paused=0')
        return q.overview()
    return q.maintenance(action,body.owner)
