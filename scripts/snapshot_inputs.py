"""Regenerate reviewed file selections from one explicit current writer slot.

Does not discover authority, stop writers, publish or overwrite existing inputs.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.storage.core import hash_file, relative_key
from api.storage.release_control import validate_source


def refresh(template, source_root):
    root = Path(source_root).resolve(strict=True)
    env = json.loads((root / 'environment.json').read_text('utf-8'))
    result = dict(template)
    result.update(source_root=str(root), catalog=env['LITLIB_DB_PATH'], research=env['LITLIB_RESEARCH_DB'])
    result['files'] = {}
    for name in template['files']:
        relative_key(name)
        source = root / 'data' / name
        if source.is_symlink() or not source.resolve().is_relative_to(root / 'data'):
            raise ValueError('Working file escapes source slot')
        sha, size = hash_file(source)
        result['files'][name] = {'source': str(source), 'sha256': sha, 'bytes': size}
    validate_source(result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--template', required=True)
    p.add_argument('--source-root', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = refresh(json.loads(Path(a.template).read_text('utf-8')), a.source_root)
    with Path(a.output).open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({'source_root': result['source_root'], 'output': str(Path(a.output).resolve()), 'published': False}))
