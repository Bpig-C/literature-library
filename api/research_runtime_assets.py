"""Scientific presentation/configuration restored locally from OSS snapshots."""
import hashlib,json,os
from pathlib import Path
from .research_context import REPO_ROOT
LEGACY={'reading': 'web/src/data/research-display-zh-CN-v1.json','ontology_display':'web/src/data/research-ontology-draft.js','baseline':'ontology/autonomy-risk-v1.json','proposal':'pilot/ontology/proposal.json','review_cards':'ontology/review-cards-v5.json'}
NAMES={'reading':'research-display.json','ontology_display':'ontology-display.json','ontology_source':'ontology-display-source.js','baseline':'autonomy-risk-v1.json','proposal':'ontology-proposal.json','review_cards':'review-cards-v5.json'}
def asset_path(name):
    if name not in NAMES:raise ValueError('unknown runtime asset')
    raw=os.environ.get('LITLIB_RESEARCH_ASSETS_ROOT')
    if raw:
        root=Path(raw)
        if not root.is_absolute():raise ValueError('runtime research assets root must be absolute')
        path=root/NAMES[name]
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('linked research asset refused')
        if not (root/'assets-manifest.json').is_file():raise ValueError('runtime research asset missing: assets-manifest.json')
        manifest=json.loads((root/'assets-manifest.json').read_text('utf-8'))
        if NAMES[name] not in manifest or not path.is_file():raise ValueError('runtime research asset missing: '+NAMES[name])
        expected=manifest[NAMES[name]]
        if not path.is_file() or path.stat().st_size!=expected['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=expected['sha256']:raise ValueError('runtime research asset integrity failed')
        return path
    if name=='ontology_source':return REPO_ROOT/LEGACY['ontology_display']
    return REPO_ROOT/LEGACY[name]

def presentation_assets():
    reading=json.loads(asset_path('reading').read_text('utf-8'))
    ontology=json.loads(asset_path('ontology_display').read_text('utf-8'))
    if not isinstance(reading.get('records'),dict) or not isinstance(ontology.get('concepts'),list):raise ValueError('runtime presentation asset shape invalid')
    return {'reading':reading,'ontology':ontology}
