"""Read-only source export: full business state, explicit exclusions, fail-closed secrets."""
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tarfile
from uuid import uuid4
import zipfile

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from backend.knowledge_packages import digest
from scripts.refresh_knowledge_packages import refresh
from scripts.migration_install import MANIFEST

EXCLUDE_PREFIXES={
    '03_local/cache':'rebuildable_cache', '03_local/.venv':'developer_environment',
    '03_local/output/macos-release':'old_installers_and_build_copies',
    '03_local/output/migration-1.0':'this_release_output',
    '03_local/output/logo-adoption-20260917':'old_local_application_build',
    '03_local/var/host-connections':'machine_account_connections',
    '03_local/var/logs':'machine_launcher_logs',
}
EXCLUDE_FILES={
    '03_local/var/auth.json':'local_authentication_state',
    '03_local/var/pi-model-checks.json':'old_machine_connection_results',
    '03_local/var/desktop-service.json':'live_process_identity',
}
SECRET_KEYS={'apikey','api_key','access_token','refresh_token','client_secret','private_key','password','authorization'}
REVIEWED=set(json.loads((APP/'native/macos/credential-review.json').read_text())['reviewed_noncredentials'])
PATTERNS=[re.compile(p) for p in (
    r'\bsk-[A-Za-z0-9_-]{20,}', r'\bgh[pousr]_[A-Za-z0-9]{25,}',
    r'\bAIza[A-Za-z0-9_-]{30,}', r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}',
    r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{24,}',
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
)]


def exclusion(relative):
    path=Path(relative)
    if relative in EXCLUDE_FILES:return EXCLUDE_FILES[relative]
    for prefix,reason in EXCLUDE_PREFIXES.items():
        if relative==prefix or relative.startswith(prefix+'/'):return reason
    if any(p in ('.git','__pycache__','.pytest_cache','.DS_Store','node_modules') for p in path.parts):return 'development_cache'
    if path.name.startswith('.env') or path.name.lower() in ('credentials.json','token.json','tokens.json'):
        return 'credential_file'
    if path.name.endswith(('.lock','-wal','-shm','.pid','.pyc')) or path.name.startswith('backend-restart-'):
        return 'transient_runtime_state'
    return None


def inventory(root):
    selected=[];excluded=[]
    for category in ('02_knowledge','03_local'):
        for directory,folders,files in os.walk(root/category,followlinks=False):
            for name in list(folders):
                path=Path(directory)/name;relative=path.relative_to(root).as_posix()
                reason=exclusion(relative)
                if reason:
                    excluded.append({'path':relative,'reason':reason,'directory':True});folders.remove(name)
                elif path.is_symlink():raise ValueError('迁移范围含符号链接：'+relative)
            for name in sorted(files):
                path=Path(directory)/name;relative=path.relative_to(root).as_posix()
                reason=exclusion(relative)
                if reason:
                    excluded.append({'path':relative,'reason':reason,'bytes':path.stat().st_size});continue
                if path.is_symlink():raise ValueError('迁移范围含符号链接：'+relative)
                if path.is_file():selected.append((relative,path))
    return selected,excluded


def quote(name):return '"'+name.replace('"','""')+'"'


def database_report(path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        result=db.execute('PRAGMA integrity_check').fetchall()
        if result!=[('ok',)]:raise ValueError('数据库完整性检查未通过：'+Path(path).name)
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name:db.execute('SELECT count(*) FROM '+quote(name)).fetchone()[0] for name in names}


def suspicious(text):
    if any(p.search(text) for p in PATTERNS):return True
    try:value=json.loads(text)
    except (ValueError,RecursionError):return False
    def check(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.lower() in SECRET_KEYS and isinstance(item,str) and len(item)>12:
                    if not any(word in item.lower() for word in ('redacted','placeholder','example','your_api','not-configured')):
                        return True
                if check(item):return True
        if isinstance(value,list):return any(check(item) for item in value)
        return False
    return check(value)


def credential_findings(path,relative):
    findings=[]
    if digest(path) in REVIEWED:return findings
    with path.open('rb') as stream:magic=stream.read(16)
    if magic==b'SQLite format 3\x00':
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                for number,row in enumerate(db.execute('SELECT * FROM '+quote(table)),1):
                    if any(isinstance(v,str) and suspicious(v) for v in row):
                        findings.append({'path':relative,'location':f'table:{table}:row:{number}','reason':'possible_credential'})
        return findings
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            total=0
            for member in archive.infolist():
                if member.is_dir():continue
                total+=member.file_size
                if total>1024*1024*1024:raise ValueError('归档内容过大，须单独检查：'+relative)
                if member.flag_bits & 1:raise ValueError('加密归档无法检查：'+relative)
                raw=archive.read(member)
                if Path(member.filename).name.lower() in ('auth.json','credentials.json','token.json','tokens.json','.env'):
                    findings.append({'path':relative,'location':member.filename,'reason':'embedded_authentication_state'})
                if hashlib.sha256(raw).hexdigest() not in REVIEWED and suspicious(raw.decode('utf-8',errors='replace')):
                    findings.append({'path':relative,'location':member.filename,'reason':'possible_credential'})
        return findings
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            total=0
            for member in archive:
                if not member.isfile():continue
                total+=member.size
                if total>1024*1024*1024:raise ValueError('归档内容过大，须单独检查：'+relative)
                raw=archive.extractfile(member).read()
                if Path(member.name).name.lower() in ('auth.json','credentials.json','token.json','tokens.json','.env'):
                    findings.append({'path':relative,'location':member.name,'reason':'embedded_authentication_state'})
                if hashlib.sha256(raw).hexdigest() not in REVIEWED and suspicious(raw.decode('utf-8',errors='replace')):
                    findings.append({'path':relative,'location':member.name,'reason':'possible_credential'})
        return findings
    if path.stat().st_size<=64*1024*1024:
        raw=path.read_bytes()
        if suspicious(raw.decode('utf-8',errors='replace')):
            findings.append({'path':relative,'reason':'possible_credential'})
    elif path.suffix.lower() in ('.json','.jsonl','.log','.txt','.csv'):
        with path.open(errors='replace') as stream:
            for number,line in enumerate(stream,1):
                if suspicious(line):findings.append({'path':relative,'location':f'line:{number}','reason':'possible_credential'})
    return findings


@contextmanager
def source_locks(root):
    from scripts.portable_runtime import service_state
    with ExitStack() as stack:
        for relative in ('.desktop.lock','03_local/var/pi-runtime.lock'):
            path=root/relative
            if path.exists():
                handle=stack.enter_context(path.open('rb'))
                try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise ValueError('信披服务仍持有工作区，请先正常退出') from None
        if (root/'01_app/backend/app.py').is_file():
            ports={8765};state=root/'03_local/var/desktop-service.json'
            if state.exists():ports.add(int(json.loads(state.read_text())['port']))
            if any(service_state(root/'01_app',port)=='ours' for port in ports):
                raise ValueError('信披服务仍在运行，请先正常退出')
        path=root/'03_local/var/conversations.sqlite3'
        if path.is_file():
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='runs' AND type='table'").fetchone()
                if exists and db.execute("SELECT count(*) FROM runs WHERE status IN ('accepted','running','cancelling')").fetchone()[0]:
                    raise ValueError('仍有未结束执行，请先在原系统完成或停止任务')
        yield


def export(root,output):
    root=Path(root).resolve()
    with source_locks(root):return _export(root,output)


def _export(root,output):
    root=Path(root).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('快照目标已存在，拒绝覆盖')
    if output.is_relative_to(root/'02_knowledge') or output.is_relative_to(root/'03_local/var'):
        raise ValueError('快照不能写入真源资料目录')
    if output.is_relative_to(root/'03_local') and not exclusion(output.relative_to(root).as_posix()):
        raise ValueError('工作区内快照须使用 03_local/output/migration-1.0，避免递归复制')
    selected,excluded=inventory(root)
    before={rel:digest(path) for rel,path in selected}
    output.mkdir(parents=True,mode=0o700)
    databases={};findings=[];credential_state_removed=[]
    try:
        for relative,path in selected:
            target=output/relative;target.parent.mkdir(parents=True,exist_ok=True)
            with path.open('rb') as stream:is_db=stream.read(16)==b'SQLite format 3\x00'
            if is_db:
                with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src:
                    with sqlite3.connect(target) as dst:src.backup(dst)
                with sqlite3.connect(target) as dst:
                    # Retired access-token digests are account state, not business history.
                    columns={row[1] for row in dst.execute('PRAGMA table_info(tokens)')}
                    if columns=={'digest','name'}:
                        count=dst.execute('SELECT count(*) FROM tokens').fetchone()[0]
                        if count:
                            dst.execute('DELETE FROM tokens');dst.commit()
                            credential_state_removed.append({'path':relative,'table':'tokens','rows':count,
                                                             'reason':'retired_authentication_digests'})
                    # Repack the copy only: remove deleted-page residue while preserving live rows.
                    dst.execute('VACUUM')
                databases[relative]=database_report(target)
            else:
                shutil.copy2(path,target)
                if digest(target)!=before[relative]:raise ValueError('复制内容不一致：'+relative)
            findings.extend(credential_findings(target,relative))
        # Do not silently redact business/audit data or make an unsafe deliverable.
        if findings:
            (output/'CREDENTIAL_REVIEW_REQUIRED.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2)+'\n')
            raise ValueError(f'检测到 {len(findings)} 处疑似凭据；快照未通过，不可分发（报告不含凭据值）')
        current,_=inventory(root)
        if {rel:digest(path) for rel,path in current}!=before:
            raise ValueError('源资料在导出期间发生变化，快照未冻结')
        # New snapshot identity only, after exact-copy verification. Originals are never edited.
        refresh(output/'02_knowledge',output/'02_knowledge/packages')
        files=[]
        for path in sorted(output.rglob('*')):
            if path.is_file():files.append({'path':path.relative_to(output).as_posix(),'bytes':path.stat().st_size,'sha256':digest(path)})
        value={'schema':'nero.disclosure.full-migration.v1','version':'1.0.0','migration_id':uuid4().hex,
               'created_at':datetime.now(timezone.utc).isoformat(),'files':files,'databases':databases,
               'excluded':excluded,'source_hashes':before,'credential_scan_findings':0,
               'reviewed_noncredential_hashes':sorted(REVIEWED),
               'credential_state_removed':credential_state_removed,
               'sqlite_copy_policy':'logical backup, authentication digest exclusion, compact copy; source unchanged',
               'credential_scan_limits':['no OCR of image-only content'],'source_modified':False}
        (output/MANIFEST).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        return value
    except BaseException:
        # Retain inspection evidence, but without a completed manifest it cannot be installed.
        (output/'NOT_FOR_DISTRIBUTION').touch()
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='仅在服务停止且获准读取全部本系统历史后导出')
    parser.add_argument('--root',type=Path,default=APP.parent)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=export(args.root,args.output)
    print(json.dumps({'migration_id':result['migration_id'],'files':len(result['files']),
                      'bytes':sum(r['bytes'] for r in result['files']),'credential_scan_findings':0},indent=2))
