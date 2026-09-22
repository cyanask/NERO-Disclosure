from pathlib import Path
import json
import os
import plistlib

import pytest
from scripts.build_macos_delta import inventory, make_delta


def bundle(root, version):
    (root/'Contents').mkdir(parents=True)
    (root/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':version,'CFBundleVersion':'1'}))
    return root


def test_only_changed_bytes_ship_and_links_and_removals_are_described(tmp_path):
    old=bundle(tmp_path/'old.app','1.0.1');new=bundle(tmp_path/'new.app','1.0.2')
    for root in [old,new]:(root/'Contents/unchanged').write_bytes(b'large runtime bytes')
    (old/'Contents/deleted').write_text('obsolete')
    (new/'Contents/added').write_text('new')
    (new/'Contents/also-added').write_text('new')
    (new/'Contents/link').symlink_to('added')
    os.chmod(new/'Contents/added',0o755)
    output=tmp_path/'delta';result=make_delta(old,new,output)
    manifest=json.loads((output/'manifest.json').read_text())
    assert 'Contents/deleted' not in manifest['after']
    assert manifest['after']['Contents/link']=={'kind':'link','link':'added'}
    assert manifest['after']['Contents/added']['mode']==0o755
    blobs=list((output/'blobs').iterdir())
    assert len(blobs)==2  # new Info.plist and one deduplicated changed-content blob
    assert all(p.read_bytes()!=b'large runtime bytes' for p in blobs)
    assert result['removed_entries']==1


def test_external_links_are_not_accepted(tmp_path):
    app=bundle(tmp_path/'app','1.0.1')
    (app/'Contents/escape').symlink_to(tmp_path)
    with pytest.raises(ValueError,match='越界'):inventory(app)
