"""Exercise an actual baseline -> current program-only update in disposable data."""
import argparse
from datetime import datetime, timezone
import http.cookiejar
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import urllib.request
from uuid import uuid4

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from scripts.validate_macos_release import code, python, command, run, start, stop, digest
from scripts.macos_bundle import verify_payload


def tree(root):
    return {p.relative_to(root).as_posix():digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def client(url):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf=None
    def request(path,body=None):
        nonlocal csrf
        headers={'Origin':url.rstrip('/')}
        if body is not None:headers.update({'Content-Type':'application/json','X-CSRF-Token':csrf})
        req=urllib.request.Request(url.rstrip('/')+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with opener.open(req,timeout=40) as response:value=json.loads(response.read())
        if path=='/api/session':csrf=value['csrf_token']
        return value
    request('/api/session')
    return request


def validate(old, new, seed, output):
    old,new,seed=map(lambda p:Path(p).resolve(),(old,new,seed))
    baseline=verify_payload(old);metadata=verify_payload(new)
    assert baseline['architecture']==metadata['architecture']
    result={'version':metadata['version'],'source_commit':metadata['source_commit'],'architecture':metadata['architecture'],
            'baseline':baseline['version'],'host_architecture':os.uname().machine,'checks':[],
            'network_model_calls':False,'independent_target_mac_verified':False,'human_acceptance':False}
    with tempfile.TemporaryDirectory(prefix='NERO 软件更新验证 ') as folder:
        folder=Path(folder).resolve();home=folder/'原有 自定义资料';target=folder/'原应用/NERO 信披系统.app'
        os_home=folder/'os-home';os_home.mkdir()
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(os_home),'LANG':'en_US.UTF-8',
             'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'}
        run(command(old,'--install-to',target,'--data-home',home,'--seed',seed),env)
        child,url=start(target,home,env,21961)
        try:
            request=client(url)
            session=request('/api/chat/sessions',{'board':'chinext','title':'升级前已有会话','request_id':str(uuid4())})
            assert session['title']=='升级前已有会话'
            blocked=subprocess.run(command(new,'--install-to',target,'--data-home',home,'--replace','--update-only'),
                env=env,capture_output=True,text=True,timeout=45)
            assert blocked.returncode!=0 and '请先退出' in blocked.stdout
            result['checks'].append('update_refuses_live_original_service')
        finally:stop(child)
        config=home/'03_local/var/pi-models.json'
        config.write_text(json.dumps({'models':[],'revision':7,'routes':{},'workflow_policy':'continuous-v1'},ensure_ascii=False))
        marker=home/'02_knowledge/user-maintained.txt';marker.write_text('接收者维护的资料')
        document=home/'03_local/work/原有文稿.docx';document.parent.mkdir(parents=True,exist_ok=True)
        run([str(python(target)),'-B','-s','-c',
             'from docx import Document;import sys;d=Document();d.add_paragraph("升级前的原有文稿");d.save(sys.argv[1])',str(document)],env)
        before={name:tree(home/name) for name in ('02_knowledge','03_local')}
        receipt=run(command(new,'--install-to',target,'--data-home',home,'--replace','--update-only'),env)
        assert 'existing_preserved' in receipt
        assert {name:tree(home/name) for name in before}==before
        result['checks'].append('knowledge_sessions_files_and_config_byte_for_byte_preserved_by_update')
        backups=list(target.parent.glob('*.previous-*.app.backup'));assert len(backups)==1
        assert plistlib.loads((backups[0]/'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']==baseline['version']
        assert verify_payload(target)['source_commit']==metadata['source_commit']
        result['checks'].append('old_application_retained_and_new_payload_verified')
        child,url=start(target,home,env,21961)
        try:
            repeated=run(command(target,'--data-home',home,'--port','21962'),env)
            assert '"event": "attached"' in repeated and url in repeated
            foreign=subprocess.run(command(target,'--data-home',folder/'另一资料目录','--port','21963'),
                env=env,capture_output=True,text=True,timeout=15)
            assert foreign.returncode!=0 and '另一资料目录' in foreign.stdout
            assert child.poll() is None
            result['checks'].append('second_launch_reuses_backend_and_other_data_root_is_blocked')
            request=client(url)
            assert request('/api/meta')['producer']['version']==metadata['version']
            settings=request('/api/chat/models')
            assert settings['configuration_path']==str(config) and settings['settings_revision']==7
            sessions=request('/api/chat/sessions?board=chinext')
            assert any(row['id']==session['id'] and row['title']=='升级前已有会话' for row in sessions)
            result['checks'].append('updated_service_reports_release_and_keeps_existing_session')
        finally:stop(child)
        assert digest(config)==before['03_local']['var/pi-models.json']
        assert digest(document)==before['03_local']['work/原有文稿.docx']
        assert marker.read_text()=='接收者维护的资料'
        verify_payload(target)
        result['checks'].append('retained_config_and_document_after_restart_and_immutable_app')
    result.update(status='passed',validated_at=datetime.now(timezone.utc).isoformat())
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--old',type=Path,required=True);parser.add_argument('--new',type=Path,required=True)
    parser.add_argument('--seed',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();validate(args.old,args.new,args.seed,args.output)
