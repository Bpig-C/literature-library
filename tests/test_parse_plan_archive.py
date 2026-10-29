import pytest
from api import parse_plans
from api.storage.core import StorageError
from test_async_parse import queue,accept,Driver
from test_foundation_plans import service


def test_budget_archive_preserves_ledger_and_fences_late_enqueue_and_resume(queue):
    pid=accept(queue,pages=1);tasks=queue.enqueue(pid)['tasks']
    queue.run_one(Driver());queue.clock.tick();queue.run_one(Driver())
    before=queue.plan_status(pid)['budget']
    result=parse_plans.archive(queue.registry,pid)
    assert result['archived'] and result['budget']==before
    with pytest.raises(StorageError,match='archived'):queue.enqueue(pid)
    with pytest.raises(StorageError,match='archived'):queue.action(tasks[0]['id'],'resume','retry old plan')
    assert queue.claim() is None
    assert parse_plans.archive(queue.registry,pid)['archived']
    fresh=accept(queue,request='fresh',pages=100)
    assert queue.enqueue(fresh)['tasks']


def test_archive_rejects_active_and_unknown_without_creating_table(queue):
    pid=accept(queue,source_ids=['SF1']);queue.enqueue(pid)
    with pytest.raises(StorageError):parse_plans.archive(queue.registry,pid)
    queue.run_one(Driver());queue.clock.tick()
    class Lost(Driver):
        def submit(self,pdf,out,event,**kwargs):
            event('submitting',backend='vlm');raise TimeoutError()
    queue.run_one(Lost())
    with pytest.raises(StorageError):parse_plans.archive(queue.registry,pid)
    with queue.registry.conn(read_only=True) as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='parse_plan_archives'").fetchone()


def test_archive_unenqueued_plan_prevents_delayed_enqueue(queue):
    pid=accept(queue)
    assert parse_plans.archive(queue.registry,pid)['archived']
    with pytest.raises(StorageError):queue.enqueue(pid)
