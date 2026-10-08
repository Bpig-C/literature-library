from scripts.restored_runtime import read_only_cli

def test_read_argument_cannot_disguise_a_mutating_subcommand():
    assert read_only_cli('litlib.py',['--library-root','/explicit','read','RS-synthetic'])
    assert not read_only_cli('litlib.py',['--library-root','/explicit','feedback-open','--detail','read'])
    assert not read_only_cli('storage_assets.py',['register','--source','read'])
    assert not read_only_cli('literature_ingest.py',['--library-root','/explicit'])
    assert read_only_cli('storage_assets.py',['check'])
