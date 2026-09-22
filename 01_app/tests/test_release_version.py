"""The released version has one source: the iteration records shown on the page."""
import json
from pathlib import Path

import pytest

from backend import version_governance
from scripts import build_macos_release, release_version

APP = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((APP / path).read_text('utf-8'))


def test_manifest_builders_and_page_share_one_version():
    notes = read('config/release-notes.json')
    assert read('BUILD_MANIFEST.json')['version'] == notes['current']
    assert release_version.current() == notes['current']
    assert build_macos_release.VERSION == notes['current']
    assert version_governance.release_notes(APP)['current'] == notes['current']


def test_current_version_carries_itemised_records():
    value = version_governance.release_notes(APP)
    current = next(row for row in value['releases'] if row['version'] == value['current'])
    assert current['released_at'] and current['kind'] and current['summary']
    assert len(current['items']) >= 5
    assert all(len(item.strip()) > 6 for item in current['items'])
    assert len(set(current['items'])) == len(current['items'])


def test_packaged_source_carries_the_iteration_records(tmp_path):
    rows = build_macos_release.copy_source(tmp_path / '01_app')
    paths = {row['path'] for row in rows}
    assert 'config/release-notes.json' in paths
    assert (tmp_path / '01_app/config/release-notes.json').is_file()


def test_missing_records_stop_instead_of_shipping_an_old_version(tmp_path):
    with pytest.raises(SystemExit):
        release_version.current(tmp_path / 'absent.json')
