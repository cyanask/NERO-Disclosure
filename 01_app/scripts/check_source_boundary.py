"""Check tracked publication paths and common credential patterns; never print matched values.

This is a small regression guard, not an exhaustive secret/security scanner.
It checks the working copy of tracked files, including hidden files and DOCX XML.
Historical commit content is reviewed separately before changing visibility.
"""
import io
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERN = re.compile(
    rb'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,})'
    rb'|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'
)
# Exact artificial value exercised by the original credential-redaction test.
SYNTHETIC = {'01_app/tests/test_pi_runtime.py': {b'sk-' + b'a' * 20}}


def findings():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    errors = []
    count = 0
    for name in filter(None, names):
        path = ROOT / name
        count += 1
        if (name.startswith(('02_knowledge/', '03_local/'))
                or any(p in name for p in ('/node_modules/', '/.venv/', '/frontend/dist/'))
                or path.suffix.lower() in {'.sqlite', '.sqlite3', '.db', '.dmg', '.p12', '.pfx', '.pem', '.key'}
                or (path.name.startswith('.env') and path.name != '.env.example')):
            errors.append((name, 'forbidden_path'))
        if path.is_symlink():
            errors.append((name, 'tracked_symlink'))
            continue
        if not path.is_file():
            errors.append((name, 'tracked_file_missing'))
            continue
        raw = path.read_bytes()
        if path.suffix.lower() == '.docx':
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                raw = b'\n'.join(archive.read(n) for n in archive.namelist() if n.endswith('.xml'))
        if b'/Users/' + b'nero/' in raw:
            errors.append((name, 'author_absolute_path'))
        if any(match.group() not in SYNTHETIC.get(name, set()) for match in PATTERN.finditer(raw)):
            errors.append((name, 'credential_pattern_candidate'))
    return count, errors


if __name__ == '__main__':
    count, errors = findings()
    for name, rule in errors:
        print(f'{rule}: {name}')
    print(f'Checked {count} tracked files; blocking findings: {len(errors)}')
    raise SystemExit(bool(errors))
