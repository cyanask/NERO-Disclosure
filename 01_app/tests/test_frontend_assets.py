import json
from pathlib import Path
import pytest
from scripts.frontend_assets import activate, archive_unused, digest, plan, references


def bundle(root, name):
    (root/'assets').mkdir(parents=True)
    (root/'index.html').write_text(f'<script src="/assets/{name}.js"></script><link href="/assets/{name}.css">')
    (root/f'assets/{name}.js').write_text(f'import("./{name}-chunk.js")')
    (root/f'assets/{name}-chunk.js').write_text('export const ready=true')
    (root/f'assets/{name}.css').write_text('body{color:black}')


def test_archive_keeps_current_and_previous_dependency_graph(tmp_path):
    root=tmp_path/'dist';bundle(root,'new')
    (root/'assets/old.js').write_text('old');previous=tmp_path/'previous.html';previous.write_text('<script src="/assets/old.js"></script>')
    (root/'assets/unused.js').write_text('unused');(root/'logo.png').write_bytes(b'logo')
    planned=plan(root,previous);assert [r['path'] for r in planned['unused']]==['assets/unused.js']
    archive=tmp_path/'archive';result=archive_unused(planned,archive)
    assert not (root/'assets/unused.js').exists()
    assert (root/'assets/new-chunk.js').exists() and (root/'assets/old.js').exists() and (root/'logo.png').exists()
    assert digest(archive/'unused/assets/unused.js')==result['moved'][0]['sha256']
    assert (archive/'bundle-before/index.html').read_bytes()==(root/'index.html').read_bytes()
    assert (archive/'previous-bundle/index.html').read_bytes()==previous.read_bytes()
    assert (archive/'previous-bundle/logo.png').exists()


@pytest.mark.parametrize('changed',['index','asset'])
def test_changed_plan_refuses_to_move_anything(tmp_path,changed):
    root=tmp_path/'dist';bundle(root,'current');unused=root/'assets/unused.js';unused.write_text('old')
    planned=plan(root)
    (root/'index.html' if changed=='index' else unused).write_text('changed')
    with pytest.raises(ValueError):archive_unused(planned,tmp_path/'archive')
    assert unused.exists()


def test_activation_and_rollback_have_complete_verified_bundles(tmp_path):
    root=tmp_path/'dist';candidate=tmp_path/'candidate';bundle(root,'old');bundle(candidate,'new')
    old=(root/'index.html').read_bytes();receipt=activate(candidate,root,tmp_path/'activation')
    assert (root/'index.html').read_bytes()==(candidate/'index.html').read_bytes()
    assert references(root)=={'assets/new.js','assets/new-chunk.js','assets/new.css'}
    manifest=json.loads((tmp_path/'activation/bundle-manifest.json').read_text())
    assert all(digest(Path(receipt['rollback'])/r['path'])==r['sha256'] for r in manifest)
    activate(receipt['rollback'],root,tmp_path/'rollback-operation')
    assert (root/'index.html').read_bytes()==old


def test_missing_dependencies_and_symlinks_fail_closed(tmp_path):
    root=tmp_path/'dist';bundle(root,'new');(root/'assets/new-chunk.js').unlink()
    with pytest.raises(ValueError):plan(root)
    (root/'assets/new-chunk.js').symlink_to(tmp_path/'outside.js');(tmp_path/'outside.js').write_text('external')
    with pytest.raises(ValueError):plan(root)


def test_vite_dependency_map_and_sibling_binary_are_retained(tmp_path):
    root=tmp_path/'dist';bundle(root,'current')
    (root/'assets/current.js').write_text('const deps=["assets/lazy.css"];new URL("data.wasm",import.meta.url)')
    (root/'assets/lazy.css').write_text('body{}');(root/'assets/data.wasm').write_bytes(b'wasm')
    keep=references(root)
    assert {'assets/lazy.css','assets/data.wasm'} <= keep
