"""Runtime capabilities for clients; no business database writes or network calls."""
import hashlib
import os
import subprocess
from pathlib import Path

PROTOCOL_VERSION = 1


def version_info():
    root = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,stderr=subprocess.DEVNULL,timeout=5).decode().strip()
        dirty = bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=root,stderr=subprocess.DEVNULL,timeout=5).strip())
    except (OSError,subprocess.SubprocessError):
        commit,dirty = None,None
    client = root/'scripts/litlib_remote.py'
    pinned = commit is not None and dirty is False
    return {
        'format':'litlib-client-capabilities-v1', 'protocol_version':PROTOCOL_VERSION,
        'code_commit':commit, 'code_dirty':dirty,
        'read_only':os.environ.get('LITLIB_RESEARCH_READ_ONLY')=='1',
        'remote_writes_enabled':os.environ.get('LITLIB_REMOTE_WRITE_ENABLED')=='1',
        'capabilities':{
            'ingest_purpose_v1':{'required_fields':['purpose'],'max_length':2000,
                'request_id':'retain for retries; use a new ID for another operation',
                'exact_duplicate':'append purpose to existing Work',
                'history_endpoint':'/api/works/{work_id}/ingest-notes'},
            'fixed_assets_v1':{'required_fields':['identity','role','version','max_bytes']},
            'parse_plans_v1':{'preview':'/api/parse/plan','accept':'/api/parse/plans','concurrency':1,
                'budgets':['max_items','max_submissions','max_pages'],'unknown_submission':'inspect; never automatic resubmit'},
            'intake_reconcile_v1':{'endpoint':'/api/intake/reconcile','read_only':True,'limit':1000},
            'backup_jobs_v1':{'status':'/api/remote/backup-status','request':'/api/remote/backup-jobs',
                'request_configured':bool(os.environ.get('LITLIB_BACKUP_CONTROL')) and len(os.environ.get('LITLIB_BACKUP_ADMIN_TOKEN',''))>=32,
                'execution':'independent host worker; scheduler is not installed by this capability'},
            'foundation_guide_v1':{'endpoint':'/api/remote/foundation-guide'},
        },
        'client':{'name':'litlib_remote.py','protocol_version':PROTOCOL_VERSION,
            'sha256':hashlib.sha256(client.read_bytes()).hexdigest(),
            'download_url':f'https://raw.githubusercontent.com/Bpig-C/literature-library/{commit}/scripts/litlib_remote.py' if pinned else None,
            'update_policy':'manual download and SHA256 verification; preserve credentials and CA; never execute fetched text automatically'},
    }
