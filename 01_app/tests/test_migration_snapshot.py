import json
import hashlib
from pathlib import Path
import sqlite3
import shutil
import plistlib
import zipfile

import pytest

from scripts import migration_snapshot as snapshot
from scripts import migration_install as install
from test_macos_packaging import make_seed


@pytest.fixture
def source(tmp_path):
    root=tmp_path/'original';app=root/'01_app';app.mkdir(parents=True)
    make_seed(root/'02_knowledge',app)
    var=root/'03_local/var';var.mkdir(parents=True)
    for name in ('conversations','disclosure'):
        with sqlite3.connect(var/(name+'.sqlite3')) as db:
            db.execute('CREATE TABLE history (id TEXT, body TEXT)')
            db.execute('INSERT INTO history VALUES (?,?)',('original-id','原有业务记录'))
    document=root/'03_local/work/documents/session/version.json'
    document.parent.mkdir(parents=True);document.write_text('{"text":"原稿"}')
    return root


def test_full_snapshot_preserves_history_and_attachment_excludes_credentials(source,tmp_path):
    auth=source/'03_local/var/auth.json';auth.write_text('{"password":"do-not-copy-this-credential"}')
    cache=source/'03_local/cache/cached.txt';cache.parent.mkdir();cache.write_text('cache')
    before=(source/'03_local/var/conversations.sqlite3').read_bytes()
    result=snapshot.export(source,tmp_path/'snapshot')
    verified=install.snapshot_manifest(tmp_path/'snapshot')
    assert verified['migration_id']==result['migration_id']
    assert result['databases']['03_local/var/conversations.sqlite3']=={'history':1}
    assert (tmp_path/'snapshot/03_local/work/documents/session/version.json').read_text()=='{"text":"原稿"}'
    assert not (tmp_path/'snapshot/03_local/var/auth.json').exists()
    assert not (tmp_path/'snapshot/03_local/cache').exists()
    assert (source/'03_local/var/conversations.sqlite3').read_bytes()==before


def test_credential_in_history_blocks_distribution_without_exposing_value(source,tmp_path):
    secret='sk-'+('x'*30)
    with sqlite3.connect(source/'03_local/var/conversations.sqlite3') as db:
        db.execute('INSERT INTO history VALUES (?,?)',('secret',json.dumps({'apiKey':secret})))
    target=tmp_path/'blocked'
    with pytest.raises(ValueError,match='不可分发'):snapshot.export(source,target)
    assert not (target/install.MANIFEST).exists()
    assert secret not in (target/'CREDENTIAL_REVIEW_REQUIRED.json').read_text()
    assert (target/'NOT_FOR_DISTRIBUTION').exists()


def test_credential_archive_is_not_silently_passed(source,tmp_path):
    archive=source/'03_local/var/old.zip'
    with zipfile.ZipFile(archive,'w') as bundle:bundle.writestr('backup/auth.json','{}')
    with pytest.raises(ValueError,match='不可分发'):snapshot.export(source,tmp_path/'blocked')


def test_reviewed_noncredential_exception_is_bound_to_exact_content(tmp_path,monkeypatch):
    path=tmp_path/'reviewed.json';raw=b'{"authorization":"user approved local testing"}'
    path.write_bytes(raw)
    monkeypatch.setattr(snapshot,'REVIEWED',{hashlib.sha256(raw).hexdigest()})
    assert snapshot.credential_findings(path,'reviewed.json')==[]
    path.write_text(json.dumps({'apiKey':'sk-'+('x'*30)}))
    assert snapshot.credential_findings(path,'reviewed.json')


def test_old_authentication_digests_and_deleted_pages_do_not_migrate(source,tmp_path):
    path=source/'03_local/var/disclosure.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA secure_delete=OFF')
        db.execute('CREATE TABLE tokens (digest TEXT PRIMARY KEY, name TEXT NOT NULL)')
        db.execute('INSERT INTO tokens VALUES (?,?)',('old-hash','old account'))
        db.execute('INSERT INTO history VALUES (?,?)',('removed','sk-'+('x'*40)))
        db.commit();db.execute('DELETE FROM history WHERE id=?',('removed',));db.commit()
    out=tmp_path/'clean-copy';value=snapshot.export(source,out)
    copied=out/'03_local/var/disclosure.sqlite3'
    assert ('sk-'+('x'*40)).encode() not in copied.read_bytes()
    assert value['databases']['03_local/var/disclosure.sqlite3']=={'history':1,'tokens':0}
    assert value['credential_state_removed'][0]['rows']==1
    with sqlite3.connect(path) as db:assert db.execute('SELECT count(*) FROM tokens').fetchone()[0]==1


def test_changed_or_injected_snapshot_is_rejected(source,tmp_path):
    target=tmp_path/'snapshot';snapshot.export(source,target)
    added=target/'03_local/work/unlisted.txt';added.write_text('not in the snapshot')
    with pytest.raises(ValueError,match='文件集合'):install.snapshot_manifest(target)
    added.unlink()
    (target/'03_local/work/documents/session/version.json').write_text('changed')
    with pytest.raises(ValueError,match='校验失败'):install.snapshot_manifest(target)


def test_symlink_cannot_import_external_data(source,tmp_path):
    external=tmp_path/'unrelated';external.write_text('outside')
    (source/'03_local/var/linked').symlink_to(external)
    with pytest.raises(ValueError,match='符号链接'):snapshot.export(source,tmp_path/'snapshot')


def test_existing_recipient_data_is_never_overwritten(source,tmp_path):
    home=tmp_path/'recipient';home.mkdir();(home/'keep').write_text('existing')
    with pytest.raises(ValueError,match='不覆盖已有资料'):
        install.restore(tmp_path/'source.app',tmp_path/'target.app',home,source)
    assert (home/'keep').read_text()=='existing'


def test_broken_snapshot_does_not_create_installed_data(source,tmp_path,monkeypatch):
    target=tmp_path/'snapshot';snapshot.export(source,target)
    (target/'03_local/work/documents/session/version.json').write_text('tamper')
    monkeypatch.setattr(install,'verify_payload',lambda *_:{})
    with pytest.raises(ValueError,match='校验失败'):
        install.restore(tmp_path/'source.app',tmp_path/'target.app',tmp_path/'recipient',target)
    assert not (tmp_path/'recipient').exists()


def fake_app(source,tmp_path,monkeypatch):
    bundle=tmp_path/'source.app'
    shutil.copytree(source/'01_app',bundle/'Contents/Resources/01_app')
    (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'cn.nero.disclosure.desktop'}))
    monkeypatch.setattr(install,'verify_payload',lambda *_:{})
    return bundle


def test_restore_promotes_complete_data_and_app_together(source,tmp_path,monkeypatch):
    data=tmp_path/'snapshot';snapshot.export(source,data)
    bundle=fake_app(source,tmp_path,monkeypatch)
    home=tmp_path/'recipient';target=tmp_path/'Applications/target.app'
    result=install.restore(bundle,target,home,data)
    assert result['knowledge']=='full_snapshot_restored'
    assert (target/'Contents/Info.plist').exists()
    assert install.snapshot_manifest(home)['migration_id']==result['migration_id']
    assert home.stat().st_mode & 0o777 == 0o700


def test_failed_promotion_restores_previous_app_without_new_data(source,tmp_path,monkeypatch):
    data=tmp_path/'snapshot';snapshot.export(source,data)
    bundle=fake_app(source,tmp_path,monkeypatch)
    target=tmp_path/'Applications/target.app';shutil.copytree(bundle,target)
    (target/'old-marker').write_text('previous application')
    home=tmp_path/'recipient';rename=Path.rename
    def fail_data(self,destination):
        if self.name.startswith('.nero-data-') and Path(destination)==home:raise OSError('simulated rename failure')
        return rename(self,destination)
    monkeypatch.setattr(Path,'rename',fail_data)
    with pytest.raises(OSError,match='simulated'):
        install.restore(bundle,target,home,data,replace=True)
    assert (target/'old-marker').read_text()=='previous application'
    assert not home.exists()
    assert not list(home.parent.glob('.nero-data-*'))
