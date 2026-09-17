"""Public source checkout: preserve local edits and expose an offline review workspace."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from scripts import dev_server


def test_first_seed_is_offline_and_restart_preserves_edits(tmp_path):
    target = dev_server.prepare_knowledge(tmp_path, tmp_path / '02_knowledge')
    catalog = target / 'data/public/boards/chinext/catalog.json'
    original = catalog.read_text()
    catalog.write_text(original + '\n')
    marker = (target / dev_server.MARKER).read_bytes()
    dev_server.prepare_knowledge(tmp_path, target)
    assert catalog.read_text() == original + '\n'
    assert (target / dev_server.MARKER).read_bytes() == marker
    assert not list(tmp_path.glob('.dev-seed-*'))
    assert not (target / 'packages/index.json').exists()  # no production package identity
    app = create_app(data_dir=tmp_path / '03_local/dev/var', seed_root=target,
                     auth_config={'allowed_hosts': ['testserver']}, pi_config={'models': []})
    with TestClient(app) as client:
        snapshot = client.get('/api/company-workspace').json()
        assert snapshot['company']['stock_code'] == '000000'
        assert snapshot['company']['verification'] is None
        assert '仅开发' in snapshot['company']['company_name']
        assert client.get('/api/library/search?board=chinext&collection=laws').status_code == 200


@pytest.mark.parametrize('marker', [None, '{}', '[]', '{broken'])
def test_unmarked_or_invalid_existing_knowledge_is_untouched(tmp_path, marker):
    target = tmp_path / '02_knowledge'
    target.mkdir()
    payload = target / 'existing.txt'
    payload.write_text('keep this data')
    if marker is not None:
        (target / dev_server.MARKER).write_text(marker)
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    with pytest.raises(SystemExit):
        dev_server.prepare_knowledge(tmp_path, target)
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before


def test_linked_root_and_nested_link_are_rejected(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = tmp_path / '02_knowledge'
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit):
        dev_server.prepare_knowledge(tmp_path, target)
    assert not list(outside.iterdir())
    target.unlink()
    dev_server.prepare_knowledge(tmp_path, target)
    (target / 'alias').symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit):
        dev_server.prepare_knowledge(tmp_path, target)
    assert not list(outside.iterdir())


def test_external_knowledge_is_also_protected_by_the_test_harness(tmp_path):
    """Exercise actual audit-hook writes in a subprocess without the parent test hook."""
    script = '''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
os.environ['NERO_DISCLOSURE_KNOWLEDGE_ROOT'] = sys.argv[2]
import conftest
root = Path(sys.argv[2]); root.mkdir()
target = root / 'original.txt'; target.write_text('keep')
conftest.pytest_sessionstart(None)
try:
    target.write_text('overwrite')
except PermissionError:
    assert target.read_text() == 'keep'
else:
    raise AssertionError('external knowledge write was not blocked')
'''
    subprocess.run([sys.executable, '-c', script, str(Path(__file__).parent),
                    str(tmp_path / 'external-knowledge')], check=True, capture_output=True)
