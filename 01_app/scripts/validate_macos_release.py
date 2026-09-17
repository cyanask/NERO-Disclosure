"""Exercise a built Release package after installation, with isolated temporary data."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def code(app):return Path(app)/'Contents/Resources/01_app'
def python(app):return code(app)/'runtime/macos/python/bin/python3.13'
def command(app,*args):return [str(python(app)),'-B','-s','-u',str(code(app)/'scripts/macos_desktop.py'),*map(str,args)]


def run(argv,env,timeout=150):
    result=subprocess.run(argv,env=env,text=True,capture_output=True,timeout=timeout)
    if result.returncode:raise AssertionError(result.stdout+'\n'+result.stderr)
    return result.stdout


def start(app,home,env,port):
    child=subprocess.Popen(command(app,'--data-home',home,'--port',port),stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
    lines=queue.Queue()
    def read():
        for line in child.stdout:lines.put(line)
        lines.put(None)
    threading.Thread(target=read,daemon=True).start()
    deadline=time.monotonic()+70;seen=[]
    try:
        while time.monotonic()<deadline:
            try:line=lines.get(timeout=.5)
            except queue.Empty:continue
            if line is None:raise AssertionError('服务提前退出：'+''.join(seen))
            seen.append(line)
            if line.startswith('NERO_EVENT '):
                value=json.loads(line[11:])
                if value['event']=='ready':return child,value['url']
                if value['event']=='error':raise AssertionError(value['message'])
        raise AssertionError('服务未在期限内就绪：'+''.join(seen))
    except Exception:
        stop(child)
        raise


def stop(child):
    if child.stdin and not child.stdin.closed:child.stdin.close()
    try:child.wait(timeout=40)
    except subprocess.TimeoutExpired:
        child.terminate()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        raise AssertionError('控制管道关闭后服务未正常退出')
    finally:
        if child.stdout:child.stdout.close()


def validate(app,seed,output):
    app,seed=Path(app).resolve(),Path(seed).resolve()
    source_hash=digest(seed/'data/public/boards/chinext/catalog.json')
    metadata=json.loads((code(app)/'MACOS_RELEASE.json').read_text())
    results={'architecture':metadata['architecture'],
             'source_commit':metadata['source_commit'],
             'payload_manifest_sha256':digest(app/'Contents/Resources/PAYLOAD_MANIFEST.json'),
             'validated_at':datetime.now(timezone.utc).isoformat(),
             'host_architecture':os.uname().machine,'checks':[], 'network_model_calls':False,
             'developer_id_signed':metadata['developer_id_signed'],'notarized':metadata['notarized'],
             'independent_target_mac_verified':False,'human_acceptance':False}
    with tempfile.TemporaryDirectory(prefix='NERO Mac迁移验证 ') as scratch:
        scratch=Path(scratch).resolve();home=scratch/'个人 数据';target=scratch/'应用 程序/NERO 信披系统.app'
        os_home=scratch/'os-home';os_home.mkdir()
        env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(os_home),'LANG':'en_US.UTF-8',
             'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'}
        installed=run(command(app,'--install-to',target,'--data-home',home,'--seed',seed),env)
        assert '"event": "installed"' in installed
        results['checks'].append('offline_install_to_new_unicode_path')
        assert not (home/'03_local/var/pi-models.json').exists()
        assert not (home/'03_local/var/disclosure.sqlite3').exists()
        assert not [p for p in (home/'02_knowledge/data/client_announcements/chinext').glob('*/catalog.json')]
        results['checks'].append('no_author_credentials_sessions_or_company_history')
        checked=run(command(target,'--data-home',home,'--check'),env)
        assert '"event": "checked"' in checked and '初始化知识库' not in checked
        results['checks'].append('bundled_python_node_pi_and_ocr_self_check')
        child,url=start(target,home,env,18865)
        try:
            cookies=http.cookiejar.CookieJar()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(cookies))
            def request(path,body=None):
                headers={'Origin':url.rstrip('/')}
                if body is not None:headers.update({'Content-Type':'application/json','X-CSRF-Token':csrf})
                req=urllib.request.Request(url.rstrip('/')+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
                with opener.open(req,timeout=40) as response:return json.loads(response.read())
            csrf=request('/api/session')['csrf_token']
            meta=request('/api/meta');assert [b['id'] for b in meta['boards'] if b['available']]==['chinext']
            models=request('/api/chat/models');assert models['installed'] is True
            assert models['configuration_path']==str(home/'03_local/var/pi-models.json'),models['configuration_path']
            assert request('/api/events?board=chinext')==[]
            cases=request('/api/library/search?board=chinext&collection=blacklist_cases');assert cases['total']==5
            laws=request('/api/library/search?board=chinext&collection=laws&q='+urllib.parse.quote('信息披露义务人'))
            assert laws['total']>0 and laws['catalog_indexed'] is True
            with opener.open(url,timeout=10) as response:assert b'<!doctype html>' in response.read().lower()
            results['checks'].append('live_webui_api_correct_data_root_empty_events_and_fts')
            managed=request('/api/library/laws/manage?board=chinext')
            row=managed['items'][0]
            changed_title='安装验收测试条目'
            updated=request('/api/library/laws/update?board=chinext',{
                'expected_fingerprint':managed['fingerprint'],'items':[{'id':row['id'],'title':changed_title}]})
            assert updated['status']=='updated'
            assert request('/api/library/items/'+row['id']+'?board=chinext')['title']==changed_title
            results['checks'].append('knowledge_edit_and_index_sync_in_user_directory')
            duplicate=run(command(target,'--data-home',home,'--port',18865),env)
            assert '"event": "attached"' in duplicate
            results['checks'].append('duplicate_launch_attaches_to_same_data_owner')
            blocked=subprocess.run(command(app,'--install-to',target,'--data-home',home,'--seed',seed,'--replace'),env=env,text=True,capture_output=True,timeout=20)
            assert blocked.returncode!=0 and '请先退出' in blocked.stdout
            results['checks'].append('update_refuses_a_live_data_owner')
        finally:stop(child)
        assert child.returncode==0 and not (home/'03_local/var/desktop-service.json').exists()
        results['checks'].append('stdin_eof_gracefully_stops_owned_service')
        content_before=digest(home/'02_knowledge/data/public/boards/chinext/catalog.json')
        result=run(command(app,'--install-to',target,'--data-home',home,'--seed',seed,'--replace'),env)
        assert 'existing_preserved' in result
        assert digest(home/'02_knowledge/data/public/boards/chinext/catalog.json')==content_before
        results['checks'].append('application_update_preserves_user_knowledge')
        moved=scratch/'换一个位置/NERO 信披系统.app';moved.parent.mkdir();shutil.move(target,moved)
        child,url=start(moved,home,env,18865)
        try:
            with urllib.request.urlopen(url+'api/library/items/'+row['id']+'?board=chinext',timeout=10) as response:
                assert json.load(response)['title']==changed_title
            results['checks'].append('app_relocation_keeps_data_and_history_paths')
        finally:stop(child)
        # Exercise Word and PDF with the packaged interpreter, not the developer environment.
        check_code='''import sys,json,io
from pathlib import Path
app=Path(sys.argv[1]);sys.path.insert(0,str(app))
from backend.document_rendering import render
from backend.document_extract import extract
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
layout=json.loads(Path(sys.argv[2]).read_text())[0]
raw=render('安装验证正文。','安装验证','测试公司',layout,'2026-09-17')
assert '安装验证正文。' in '\\n'.join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
w=PdfWriter();p=w.add_blank_page(width=612,height=792)
font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
stream=DecodedStreamObject();stream.set_data(b'BT /F1 26 Tf 40 650 Td (NERO PACKAGING 2026) Tj ET');p[NameObject('/Contents')]=w._add_object(stream)
pdf=Path(sys.argv[3]);w.write(pdf)
result=extract(pdf)
assert 'NERO' in result['pages'][0]['text'],result
assert result['pages'][0]['method']=='apple_vision',result
print(json.dumps({'word_roundtrip':True,'pdf_ocr':True,'ocr_review_required':result['needs_review']}))
'''
        output_text=run([str(python(moved)),'-B','-s','-c',check_code,str(code(moved)),
                        str(home/'02_knowledge/templates/boards/chinext/layout_profiles.json'),str(scratch/'sample.pdf')],env)
        assert '"word_roundtrip": true' in output_text and '"pdf_ocr": true' in output_text
        results['checks'].append('packaged_word_roundtrip_and_native_pdf_ocr')
        verify='import sys;sys.path.insert(0,sys.argv[1]);from scripts.macos_bundle import verify_payload;verify_payload(sys.argv[2]);print("unchanged")'
        assert 'unchanged' in run([str(python(moved)),'-B','-s','-c',verify,str(code(moved)),str(moved)],env)
        results['checks'].append('read_only_app_payload_unchanged_after_use')
    assert digest(seed/'data/public/boards/chinext/catalog.json')==source_hash
    results.update(status='passed',source_knowledge_unchanged=True)
    Path(output).write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--seed',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();validate(args.app,args.seed,args.output)
