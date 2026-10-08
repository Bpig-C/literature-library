import hashlib
import pytest
from api.storage.authority import Authority
from api.storage.backends import LocalObjectBackend
from api.storage.core import Namespace,StorageError

def test_handover_fences_old_writer_and_wrong_owner(tmp_path):
    backend=LocalObjectBackend(tmp_path/'remote');ns=Namespace('research/agent-loss-of-control/literature/test/authority/')
    a=Authority(backend,ns.root,'A'*32,0,tmp_path/'A');a.initialize()
    wrong=Authority(backend,ns.root,'B'*32,0,tmp_path/'wrong')
    with pytest.raises(StorageError):
        with wrong.write_guard():pass
    with a.write_guard():pass
    a.freeze()
    release={'manifest_sha256':'1'*64,'manifest_key':ns.key('1'*64)}
    a.handover(hashlib.sha256(('B'*32).encode()).hexdigest(),release)
    with pytest.raises(StorageError):
        with a.write_guard():pass
    # Even a restored old owner without its local freeze marker is fenced.
    stale=Authority(backend,ns.root,'A'*32,0,tmp_path/'stale')
    with pytest.raises(StorageError):stale.check_remote()
    b=Authority(backend,ns.root,'B'*32,1,tmp_path/'B',release['manifest_sha256'])
    with b.write_guard():pass
    assert b.read(1)['release']==release

def test_new_owner_cannot_write_from_wrong_or_unspecified_release(tmp_path):
    backend=LocalObjectBackend(tmp_path/'remote');ns=Namespace('research/agent-loss-of-control/literature/test/wrong-release/')
    a=Authority(backend,ns.root,'A'*32,0,tmp_path/'A');a.initialize()
    release={'manifest_sha256':'3'*64,'manifest_key':ns.key('3'*64)}
    a.handover(hashlib.sha256(('B'*32).encode()).hexdigest(),release)
    for sha in (None,'4'*64):
        b=Authority(backend,ns.root,'B'*32,1,tmp_path/str(sha),sha)
        with pytest.raises(StorageError,match='exact handover release'):
            with b.write_guard():pass
    b=Authority(backend,ns.root,'B'*32,1,tmp_path/'correct','3'*64)
    with b.write_guard():pass

def test_failed_handover_keeps_source_frozen_and_retry_exact(tmp_path):
    backend=LocalObjectBackend(tmp_path/'remote');ns=Namespace('research/agent-loss-of-control/literature/test/handover-failure/')
    a=Authority(backend,ns.root,'A'*32,0,tmp_path/'A');a.initialize();put=backend.put_immutable
    def fail(*args):raise StorageError('network_unavailable','synthetic offline')
    backend.put_immutable=fail
    target=hashlib.sha256(('B'*32).encode()).hexdigest();release={'manifest_sha256':'2'*64,'manifest_key':ns.key('2'*64)}
    with pytest.raises(StorageError):a.handover(target,release)
    with pytest.raises(StorageError):
        with a.write_guard():pass
    backend.put_immutable=put;a.handover(target,release);assert a.handover(target,release)['epoch']==1
