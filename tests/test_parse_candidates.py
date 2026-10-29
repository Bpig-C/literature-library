from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routes import parse
from api import db
from test_foundation_plans import service,sqlite_read


def test_pipeline_candidates_are_source_bound_read_only_and_latest(service,monkeypatch):
    with service.registry.conn(write=True) as c:
        c.execute('ALTER TABLE works ADD COLUMN title TEXT')
        c.execute("UPDATE works SET title='Synthetic title'")
        c.execute("ALTER TABLE source_files ADD COLUMN file_ext TEXT DEFAULT '.pdf'")
        c.execute("INSERT INTO literature_parse_runs(id,work_id,source_file_id,status,started_at) VALUES('old','W1','SF1','succeeded','2026-01-01')")
        c.execute("INSERT INTO literature_parse_runs(id,work_id,source_file_id,status,started_at) VALUES('new','W1','SF1','pending','2026-10-01')")
        c.execute("UPDATE source_files SET status='quarantined' WHERE id='SF2'")
    monkeypatch.setattr(db,'get_read_conn',lambda:sqlite_read(service.registry.catalog))
    app=FastAPI();app.include_router(parse.router,prefix='/api')
    result=TestClient(app).get('/api/parse/candidates')
    assert result.status_code==200
    payload=result.json()
    assert payload['counts']['pending']==1
    assert [(r['id'],r['source_file_id'],r['work_id'],r['status']) for r in payload['items']]==[('SF1','SF1','W1','pending')]
