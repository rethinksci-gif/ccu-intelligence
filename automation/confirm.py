"""Create and verify a deployment receipt; a successful deploy API response is not confirmation."""
import argparse
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def receipt(root, revision):
    # Hash actual HTML bytes, including every new publication and both language variants.
    pages = {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob('*.html')}
    if not pages:
        raise ValueError('build contains no pages')
    publications = sorted(p.stem for p in Path('automation/publications').glob('*.json'))
    return {'revision': revision, 'pages': pages, 'publications': publications}


def confirm(base, expected, fetch=None):
    def get(path):
        with urllib.request.urlopen(base.rstrip('/') + '/' + path + '?revision=' + expected['revision'], timeout=30) as r:
            return r.read()
    fetch = fetch or get
    actual = json.loads(fetch('publication-receipt.json'))
    if actual != expected:
        raise ValueError('live publication receipt does not match expected build')
    for path, expected_hash in expected['pages'].items():
        if sha(fetch(path)) != expected_hash:
            raise ValueError('live content mismatch: ' + path)
    return {'status': 'confirmed', 'revision': expected['revision'], 'pages': len(expected['pages']),
            'last_publication': (expected.get('publications') or [None])[-1],
            'confirmed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['prepare', 'confirm'])
    p.add_argument('--root', type=Path)
    p.add_argument('--base')
    a = p.parse_args()
    expected_path = Path('automation/expected-receipt.json')
    if a.mode == 'prepare':
        data = receipt(a.root, os.environ.get('GITHUB_SHA', 'local'))
        expected_path.parent.mkdir(exist_ok=True)
        expected_path.write_text(json.dumps(data, sort_keys=True))
        (a.root / 'publication-receipt.json').write_text(json.dumps(data, sort_keys=True))
    else:
        expected = json.loads(expected_path.read_text())
        for attempt in range(4):
            try:
                result = confirm(a.base, expected)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(10)  # bounded CDN propagation retry, never report unconfirmed success
        Path('automation/confirmation.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))


if __name__ == '__main__':
    main()
