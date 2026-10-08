"""Deployment publication check; distinct from research documentation governance."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=('output/','works/','_archive/','_analysis_outbox/','pilot/','ontology/','.workbuddy/','web/src/data/research-display-zh-CN-v1.json')
def check():
    paths=subprocess.check_output(['git','ls-tree','-r','--name-only','-z','HEAD'],cwd=ROOT).decode().rstrip('\0').split('\0')
    errors=[]
    for name in paths:
        if name.startswith(FORBIDDEN) or Path(name).suffix.lower() in {'.sqlite','.pdf','.zip','.csv','.db'} or name=='.env':errors.append('research/runtime/credential path in code: '+name)
    if subprocess.check_output(['git','rev-list','--count','HEAD'],cwd=ROOT).decode().strip()!='1':errors.append('release history must be a clean root, without broad-content ancestors')
    required={'README.md','docs/deployment.md','docs/architecture.md','pyproject.toml','uv.lock','web/npm-shrinkwrap.json','contracts/research-workflow-v1.json','api/storage/unified_release.py','scripts/storage_release.py','api/research_runtime_assets.py'}
    errors+=['required deployment source absent: '+p for p in sorted(required-set(paths))]
    if (ROOT/'web/src/data/research-ontology-draft.js').is_file() and (ROOT/'web/src/data/research-ontology-draft.js').stat().st_size>2000:errors.append('ontology code wrapper unexpectedly contains business data')
    return {'ok':not errors,'errors':errors,'tracked_files':len(paths),'scope':'code publication whitelist/history/required deployment sources; not full research governance docs or scientific validation','files':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}}
if __name__=='__main__':
    result=check();print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['ok'] else 1)
