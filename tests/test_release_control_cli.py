import json,subprocess,sys
from pathlib import Path
import pytest
from test_unified_release import release,CODE
from api.storage.release_control import prepare,stage,publish,digest
from api.storage.core import StorageError,hash_file

def inputs(release):
    root,backend,ns,_,_,_,_,config,code,files,front=release
    return {'format':'litlib-snapshot-input-v1','namespace':ns,'catalog':str(root/'library/literature.sqlite'),'research':str(root/'research/research.sqlite'),'files':{name:{'source':str(p),'sha256':hash_file(p)[0],'bytes':hash_file(p)[1]} for name,p in files.items()},'configuration':config,'code_url':str(CODE),'frontend':{'source':str(front),'sha256':hash_file(front)[0],'bytes':hash_file(front)[1]}}

def test_snapshot_cli_prepare_stage_publish_restore(release,tmp_path):
    data=inputs(release);input_path=tmp_path/'inputs.json';input_path.write_text(json.dumps(data),'utf-8');ticket_path=tmp_path/'ticket.json'
    def cli(*args):
        result=subprocess.run([sys.executable,str(CODE/'scripts/storage_release.py'),*map(str,args)],cwd=CODE,capture_output=True,text=True,encoding='utf-8')
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    prepared=cli('snapshot-prepare','--inputs',input_path,'--ticket',ticket_path,'--max-snapshot-bytes',10*1024**2)
    assert prepared['source_writes'] is False and prepared['network_requests']==0
    staged=cli('snapshot-stage','--ticket',ticket_path,'--approved-ticket-sha256',prepared['ticket_sha256'],'--destination',tmp_path/'stage','--writers-stopped')
    published=cli('snapshot-publish','--stage',tmp_path/'stage','--approved-manifest-sha256',staged['manifest_sha256'],'--max-upload-bytes',staged['maximum_upload_bytes'],'--local-objects',release[1].root)
    assert published['state']=='published' and published['manifest_published_last']
    restored=cli('restore','--manifest-key',published['manifest_key'],'--manifest-sha256',published['manifest_sha256'],'--namespace',release[2],'--destination',tmp_path/'client','--expected-git-url',CODE,'--local-objects',release[1].root)
    assert restored['credentials_copied'] is False
    check=subprocess.run([sys.executable,str(tmp_path/'client/app/scripts/restored_runtime.py'),'check','--root',str(tmp_path/'client')],capture_output=True,text=True,encoding='utf-8')
    assert check.returncode==0,check.stderr
    assert json.loads(check.stdout)['fallback_to_source_machine'] is False

def test_snapshot_budget_approval_freeze_and_upload_retry(release,tmp_path):
    data=inputs(release)
    with pytest.raises(StorageError):prepare(data,1)
    ticket=prepare(data,10*1024**2);approval=digest(ticket)
    with pytest.raises(StorageError):stage(ticket,'0'*64,tmp_path/'denied',True)
    with pytest.raises(StorageError):stage(ticket,approval,tmp_path/'no-window',False)
    receipt=stage(ticket,approval,tmp_path/'stage',True)
    state={'calls':0}
    def fault(key):
        state['calls']+=1
        if state['calls']==2:raise RuntimeError('synthetic interrupted upload')
    with pytest.raises(RuntimeError):publish(tmp_path/'stage',receipt['manifest_sha256'],release[1],receipt['maximum_upload_bytes'],fault)
    assert json.loads((tmp_path/'stage/upload-journal.json').read_text())['state']=='publishing'
    result=publish(tmp_path/'stage',receipt['manifest_sha256'],release[1],receipt['maximum_upload_bytes'])
    assert result['state']=='published'
    # Finished staging resumes frozen bytes even if the source working draft changes.
    next(iter(data['files'].values()))
    draft=Path(data['files']['research/editing/working.md']['source']);draft.write_text('new live draft','utf-8')
    assert stage(ticket,approval,tmp_path/'stage',True)==receipt
    with pytest.raises(StorageError):stage(ticket,approval,tmp_path/'different-stage',True)
    with pytest.raises(StorageError):publish(tmp_path/'stage',receipt['manifest_sha256'],release[1],1)
