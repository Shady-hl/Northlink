"""Package only a clean committed tree, after its tests pass.

Usage: python scripts/build_release.py /absolute/path/Northlink-release.zip
Dependencies must already be installed in the chosen Python environment.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Provide the output ZIP path.')
    output = Path(sys.argv[1]).resolve()
    if output.exists():
        raise SystemExit('Output exists; choose a new filename to preserve it.')
    if git('status', '--porcelain').strip():
        raise SystemExit('Commit the intended changes first; working tree is not clean.')
    tests = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
                           cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if tests.returncode:
        print(tests.stdout)
        raise SystemExit('Tests failed; no ZIP created.')
    entries = {}
    for name in git('ls-files', '-z').decode().split('\0'):
        if not name:
            continue
        p = Path(name)
        if any(part in ('.git', '.venv', 'data', '__pycache__') for part in p.parts) or p.name == '.env' or p.suffix == '.db':
            raise SystemExit('Excluded local file is tracked: ' + name)
        data = (ROOT / name).read_bytes()
        if re.search(rb'sk-[A-Za-z0-9]{20,}|ANTHROPIC_AUTH_TOKEN\s*=\s*[^\s\n]+', data) and p.name != 'make_review_zip.sh':
            raise SystemExit('Possible credential pattern: ' + name)
        entries[name] = data
    commit = git('rev-parse', 'HEAD').decode().strip()
    entries['TEST_RESULTS.txt'] = tests.stdout.encode()
    entries['COMMIT.txt'] = f'Release commit: {commit}\nPython: {sys.version.split()[0]}\n'.encode()
    manifest = {'release_commit': commit, 'created_at': datetime.now(timezone.utc).isoformat(),
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(entries.items())}}
    entries['RELEASE_MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'x', ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = ZipInfo('Northlink/' + name)
            info.create_system = 3
            info.compress_type = ZIP_DEFLATED
            source = ROOT / name
            mode = source.stat().st_mode if source.is_file() else 0o100644
            info.external_attr = (mode & 0xFFFF) << 16
            archive.writestr(info, data)
    print(tests.stdout.strip())
    print(f'Packaged {len(entries)} files at {output} ({output.stat().st_size:,} bytes)')
    print('Release commit: ' + commit)


if __name__ == '__main__':
    main()
