"""Integrity of automatic publication records; called by CI and before committing content."""
import hashlib
import json
from pathlib import Path


def validate(root=Path('.')):
    for path in (root/'automation/publications').glob('*.json'):
        publication=json.loads(path.read_text())
        files=publication.get('files') or {publication['file']:publication['sha256']}
        if not publication.get('items') or any(i.get('status')!='VERIFIED' or i.get('reasons') for i in publication['items']):
            raise ValueError('publication contains unverified items: '+str(path))
        for name, expected in files.items():
            target=(root/name).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError('publication path escapes repository')
            if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
                raise ValueError('publication changed after verification: '+name)
            content=target.read_text()
            if publication['id'] not in content:
                raise ValueError('publication identifier missing')
            for item in publication['items']:
                if item['source_url'] not in content:
                    raise ValueError('source reference missing from publication')
    print('Automatic publication manifests verified')


if __name__=='__main__':
    validate()
