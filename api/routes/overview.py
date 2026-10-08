"""Read-only collection coverage, kept separate from scientific quality claims."""
from collections import Counter
from contextlib import closing
from pathlib import Path
import sqlite3

from fastapi import APIRouter
from ..db import DB_PATH, LIBRARY_ROOT
from ..research_context import get_research_context
from ..research_service import ResearchService
from ..storage.runtime import material_ready

router = APIRouter()


def collection_overview(db_path: Path, root: Path) -> dict:
    with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        works = conn.execute('SELECT id,read_status FROM works').fetchall()
        active = {r['id'] for r in works if r['read_status'] != 'quarantined'}
        sources = conn.execute('SELECT id,work_id,source_path,status FROM source_files').fetchall()
        runs = conn.execute("SELECT * FROM literature_parse_runs WHERE status='succeeded' ORDER BY finished_at DESC,id DESC").fetchall()
        parsed_sources = set()
        for run in runs:
            value = run['content_md_path']
            if value:
                path = Path(value)
                if not path.is_absolute():
                    path = root / path
                if material_ready(path):
                    parsed_sources.add(run['source_file_id'])
        current = [r for r in sources if r['status'] == 'active' and r['work_id'] in active]
        parsed_works = {r['work_id'] for r in current if r['id'] in parsed_sources}
        relations = dict(conn.execute('SELECT relation_type,COUNT(*) FROM work_relations GROUP BY relation_type').fetchall())
        return {'works': len(works), 'active_works': len(active), 'quarantined_works': len(works)-len(active),
                'sources': len(sources), 'active_sources': len(current),
                'parsed_works': len(parsed_works), 'parsed_sources': sum(r['id'] in parsed_sources for r in current),
                'without_usable_parse': len(active-parsed_works), 'relations': relations,
                'citation_graph_status': 'research_store'}


@router.get('/overview')
def overview():
    result = collection_overview(DB_PATH, LIBRARY_ROOT)
    ctx = get_research_context()
    result['research'] = {'available': False, 'batches': []}
    if not ctx.db_path.is_file():
        return result
    try:
        research_service = ResearchService(ctx)
        with closing(ctx.connect(read_only=True)) as conn:
            columns = {r[1] for r in conn.execute('PRAGMA table_info(research_source_records)')}
            v5 = 'content_state' in columns
            batches = []
            batch_columns = {r[1] for r in conn.execute('PRAGMA table_info(research_batches)')}
            release_field = 'release_id' if 'release_id' in batch_columns else 'NULL AS release_id'
            parent_field = ('parent_batch_id' if 'parent_batch_id' in batch_columns
                            else 'NULL AS parent_batch_id')
            status_field = 'status' if 'status' in batch_columns else 'NULL AS status'
            created_field = ('created_at' if 'created_at' in batch_columns
                             else 'NULL AS created_at')
            batch_rows = conn.execute(
                f'''SELECT id,name,{release_field},{parent_field},{status_field},{created_field}
                    FROM research_batches ORDER BY created_at DESC,id'''
            ).fetchall()
            child_ids = {}
            for row in batch_rows:
                if row['parent_batch_id']:
                    child_ids.setdefault(row['parent_batch_id'], []).append(row['id'])
            for batch in batch_rows:
                fields = '''s.work_id,t.parse_quality,
                    sr.id AS source_record_id,sr.agent_review_status AS source_review,
                    i.id AS interpretation_id,i.agent_review_status AS interpretation_review,
                    i.validity_status AS interpretation_validity'''
                if v5:
                    fields += ',sr.content_state AS source_content,i.content_state AS interpretation_content'
                items = conn.execute(f'''SELECT {fields}
                    FROM research_batch_items bi JOIN research_sources s ON s.id=bi.source_id
                    JOIN research_text_snapshots t ON t.id=bi.snapshot_id
                    LEFT JOIN research_source_records sr ON sr.id=bi.source_record_id
                    LEFT JOIN research_interpretations i ON i.id=bi.interpretation_id
                    WHERE bi.batch_id=?''', (batch['id'],)).fetchall()
                successors = child_ids.get(batch['id'], [])
                batch_entry = {'id': batch['id'], 'name': batch['name'], 'works': len({r['work_id'] for r in items}),
                    'release_id': batch['release_id'],
                    'parent_batch_id': batch['parent_batch_id'],
                    'status': batch['status'],
                    'created_at': batch['created_at'],
                    'successor_batch_ids': successors,
                    'is_current_round': not successors,
                    'source_records': sum(bool(r['source_record_id']) for r in items),
                    'source_reviewed': sum(r['source_review']=='approved' for r in items),
                    'interpretations': sum(bool(r['interpretation_id']) for r in items),
                    'stale': sum(r['interpretation_validity']=='stale' for r in items),
                    'parse_quality': dict(Counter(r['parse_quality'] for r in items))}
                if v5:
                    # Keep the dashboard on the same consumption contract as
                    # query/matrix/export.  Counting two ``stable`` labels here
                    # used to ignore validation/review/validity, compatible C
                    # lineage, requested unit coverage and legitimate C-only
                    # commissions, so the overview could disagree with the
                    # batch's canonical usable-basis endpoint.
                    usable = research_service.usable_basis(batch['id'])
                    batch_entry['usable_items'] = usable['usable_count']
                    batch_entry['usable_total'] = usable['total']
                    batch_entry['source_content_states'] = dict(
                        Counter(r['source_content'] for r in items if r['source_content']))
                    batch_entry['interpretation_content_states'] = dict(
                        Counter(r['interpretation_content'] for r in items if r['interpretation_content']))
                batches.append(batch_entry)
            research_tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            citation_graph = {
                'available': {'research_reference_objects', 'research_cites'} <= research_tables,
                'references': 0,
                'matched_references': 0,
                'edges': 0,
                'verified_edges': 0,
            }
            if citation_graph['available']:
                citation_graph.update({
                    'references': conn.execute(
                        'SELECT COUNT(*) FROM research_reference_objects').fetchone()[0],
                    'matched_references': conn.execute(
                        "SELECT COUNT(*) FROM research_reference_objects WHERE match_status='matched'"
                    ).fetchone()[0],
                    'edges': conn.execute('SELECT COUNT(*) FROM research_cites').fetchone()[0],
                    'verified_edges': conn.execute(
                        'SELECT COUNT(*) FROM research_cites WHERE verified=1').fetchone()[0],
                })
            result['research'] = {'available': True, 'batches': batches,
                                  'content_states': v5,
                                  'citation_graph': citation_graph,
                                  'consumption_rule': '可用基线=两层内容稳定（结构验证+独立审查）；人工采纳是叠加判断，不阻断使用' if v5 else None}
    except sqlite3.Error:
        result['research']['error'] = '研究库暂不可读取，请检查研究库配置或结构。'
    return result
