"""Original-preserving imports shared by the browser and existing Pi runtime."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path, PureWindowsPath
from uuid import uuid4
from fastapi import HTTPException
from . import paths as workspace_paths, public_sources, library_admin, announcement_history as history
from .boards import require_board
from .document_extract import extract, ocr, pdf_blocks
from .announcement_tags import document_kind

MAX_BYTES=30*1024*1024


def _safe_path(root,path):
    """Resolve a lexical workspace path without following any child link."""
    base=Path(root).absolute();path=Path(path).absolute()
    if base.is_symlink():raise HTTPException(409,'资料发布根目录含路径别名')
    try:relative=path.relative_to(base)
    except ValueError:raise HTTPException(409,'资料发布路径超出当前工作区') from None
    current=base
    for part in relative.parts:
        current=current/part
        if current.is_symlink():raise HTTPException(409,'资料发布路径含符号链接，未继续写入')
    return path


def _safe_registered(root,relative):
    if not isinstance(relative,str):raise HTTPException(409,'旧登记路径格式无效')
    raw=relative.replace('\\','/')
    parsed=Path(raw)
    if (not raw or parsed.is_absolute() or PureWindowsPath(raw).drive
            or '..' in parsed.parts or '\x00' in raw):raise HTTPException(409,'旧登记路径不属于当前工作区')
    base=Path(workspace_paths.base_for(root,raw)).absolute()
    return _safe_path(base,base/parsed)


def _registered_file(root,relative,expected=None):
    path=_safe_registered(root,relative)
    if not path.is_file():raise HTTPException(409,'已登记文件不存在或不是普通文件')
    actual=library_admin.sha(path.read_bytes())
    if expected is not None and actual!=expected:raise HTTPException(409,'已登记原件或解析版本哈希不一致')
    return path


def _receipt_path(root,identity,name='receipt.json'):
    if not re.fullmatch(r'[a-f0-9-]{36}',identity):raise HTTPException(422,'导入编号无效')
    local=Path(workspace_paths.local_of(root)).absolute()
    return _safe_path(local,local/'work/library-imports'/identity/name)


def _publish_immutable(root,path,raw,expected,label):
    if library_admin.sha(raw)!=expected:raise HTTPException(409,label+'内容哈希不符，未发布')
    path=_safe_path(root,path)
    if path.is_symlink():raise HTTPException(409,label+'已是符号链接，未覆盖')
    if path.exists():
        if not path.is_file() or library_admin.sha(path.read_bytes())!=expected:
            raise HTTPException(409,label+'已存在但哈希不一致，未覆盖')
        return False
    path.parent.mkdir(parents=True,exist_ok=True);_safe_path(root,path)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with open(fd,'wb',closefd=True) as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        linked=False
        try:os.link(name,path);linked=True
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or library_admin.sha(path.read_bytes())!=expected:
                raise HTTPException(409,label+'在发布期间发生冲突，未覆盖')
        except OSError as exc:
            raise HTTPException(409,label+'不可变发布失败，未覆盖') from exc
        return linked
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(409,label+'不可变发布失败，未覆盖') from exc
    finally:
        if os.path.exists(name):os.unlink(name)


def _verify_row_assets(root,row):
    for path_key,hash_key in (('original_path','sha256'),('document_path','document_sha256')):
        if row.get(path_key):_registered_file(root,row[path_key],row.get(hash_key))


def _document_target(root,target,source_sha,document_raw,references=()):
    """Keep an existing parse version and publish changed bytes under its own hash."""
    document_sha=library_admin.sha(document_raw)
    canonical=target/(source_sha+'.json');_safe_path(root,canonical)
    canonical_relative=workspace_paths.store_path(root,canonical)
    for row in references:
        if row.get('document_path')==canonical_relative:
            _registered_file(root,row['document_path'],row.get('document_sha256'))
    if canonical.is_symlink():raise HTTPException(409,'既有解析版本是符号链接，未覆盖')
    if canonical.is_file() and library_admin.sha(canonical.read_bytes())==document_sha:return canonical,document_sha
    path=target/(document_sha+'.json')
    _publish_immutable(root,path,document_raw,document_sha,'解析版本')
    return path,document_sha



def classify(title):
    """Retained name for existing callers; the title rules live in announcement_tags."""
    return document_kind(title)




def prepare(root, board, collection, raw, filename, company='', url='', owner='web'):
    require_board(board)
    if collection not in ('laws','cases','blacklist_cases','history','profiles'):raise HTTPException(422,'资料库无效')
    if not raw or len(raw)>MAX_BYTES:raise HTTPException(413,'单文件须小于30MB')
    if collection=='history':history.company_key(company)
    identity=str(uuid4());local=Path(workspace_paths.local_of(root)).absolute();base=local/'work/library-imports'/identity
    _safe_path(local,base);base.mkdir(parents=True);_safe_path(local,base)
    suffix='.pdf' if raw.startswith(b'%PDF-') else '.html' if raw.lstrip().lower().startswith((b'<!doctype',b'<html')) else '.docx'
    path=base/('original'+suffix);library_admin.atomic(path,raw)
    try:parsed=extract(path)
    except HTTPException:raise
    except (ValueError,KeyError,zipfile.BadZipFile,subprocess.SubprocessError) as exc:raise HTTPException(422,'文件抽取失败，原件已保留，请检查文件或重试') from exc
    text='\n'.join(p['text'] for p in parsed['pages'])
    titles=[x.strip() for x in text.splitlines() if x.strip() and not x.strip().startswith(('证券代码','公告编号','证券简称'))]
    fields=history.extract_fields(text)
    value={'id':identity,'board':board,'collection':collection,'company':company,'owner':owner,'filename':Path(filename).name,
        'source_url':url,'original_path':workspace_paths.store_path(root,path),'sha256':library_admin.sha(raw),'document':parsed,
        'fields':fields,'suggested_title':(titles[0][:150] if titles else Path(filename).stem),'created_at':history.now(),'status':'prepared'}
    value['suggested_kind']=classify(''.join(titles[:4]))
    library_admin.atomic(_receipt_path(root,identity),history.encoded(value))
    return value


def get(root, identity, board, collection=None, company=None, owner=None):
    if not re.fullmatch(r'[a-f0-9-]{36}',identity):raise HTTPException(422,'导入编号无效')
    path=_receipt_path(root,identity)
    if not path.is_file():raise HTTPException(404,'导入记录不存在')
    value=json.loads(path.read_text())
    if value['board']!=board or collection is not None and value['collection']!=collection or company is not None and value['company']!=company:
        raise HTTPException(403,'导入记录不属于当前公司或资料库')
    if owner is not None and value['owner'] not in ('web',owner):raise HTTPException(403,'导入记录属于其他任务')
    _registered_file(root,value['original_path'],value['sha256'])
    return value


def commit(root, identity, board, collection, company, metadata, actor, expected=None):
    source=get(root,identity,board,collection,company)
    if source['status']=='applied':
        result=source['result']
        if collection=='history' and result.get('index',{}).get('status')!='current':
            from .announcement_index import sync
            result['index']={'status':'current',**sync(root,board,company)}
            source['result']=result;library_admin.atomic(_receipt_path(root,identity),history.encoded(source))
        return result
    if not isinstance(metadata,dict):raise HTTPException(422,'导入元数据无效')
    document=source['document'];text='\n'.join(p['text'] for p in document['pages'])
    if document['requires_ocr']:raise HTTPException(409,'存在无法读取的页面，先完成提取核对')
    if document['needs_review'] and metadata.get('extraction_confirmed') is not True:raise HTTPException(409,'请核对 OCR、图片或修订部分后确认抽取内容')
    if not metadata.get('title','').strip():raise HTTPException(422,'请填写资料标题')
    if collection=='profiles':raise HTTPException(422,'模板请使用上传替换或新模板登记')
    current=history.state(root,board,company) if collection=='history' else library_admin.state(root,collection,board)
    if expected is not None and current['fingerprint']!=expected:
        raise HTTPException(409,'资料库版本已变化，请重新读取后确认')
    source_path=_registered_file(root,source['original_path'],source['sha256'])
    raw_bytes=source_path.read_bytes()
    duplicate=None
    if collection!='history':
        duplicate=next((r for r in current['items'] if r.get('sha256')==source['sha256']),None)
        if duplicate:
            _verify_row_assets(root,duplicate)
            result={'status':'already_present','id':duplicate['id'],'fingerprint':current['fingerprint']}
            source.update(status='applied',result=result)
            library_admin.atomic(_receipt_path(root,identity),history.encoded(source))
            return result
    if collection=='history':
        codes=set(re.findall(r'证券代码[:：\s]*(\d{6})',text))
        if codes and codes!={company}:raise HTTPException(422,'原文证券代码与当前公司不一致')
        if not codes and not metadata.get('company_confirmed'):raise HTTPException(409,'原文未识别证券代码，请核对公司归属')
        duplicate=next((r for r in current['items'] if r.get('sha256')==source['sha256'] and not r.get('deleted_at')),None)
        if duplicate:
            _verify_row_assets(root,duplicate)
            try:
                if date.fromisoformat(str(metadata.get('published_at'))) > date.today():raise ValueError()
            except (TypeError,ValueError):raise HTTPException(422,'发布日期无效或晚于今天')
            if metadata.get('publication_confirmed') is not True:raise HTTPException(422,'请确认这是已正式发布的公告；工作稿不能进入历史公告库')
            if not library_admin.official_url(metadata.get('url') or source['source_url']):raise HTTPException(422,'请提供交易所、巨潮等官方发布链接')
            if not current.get('company_name'):raise HTTPException(422,'请先登记当前公司')
            from .announcement_index import status as index_status
            result={'id':duplicate['id'],'status':'already_present','fingerprint':current['fingerprint'],
                    'index':index_status(root,board,company)}
            source.update(status='applied',result=result)
            library_admin.atomic(_receipt_path(root,identity),history.encoded(source))
            return result
    document_raw=history.encoded(document)
    target=history.directory(root,board,company)/'originals' if collection=='history' else workspace_paths.data(root)/'public/originals'
    _safe_path(root,target);target.mkdir(parents=True,exist_ok=True);_safe_path(root,target)
    suffix=Path(source['original_path']).suffix
    original=target/(source['sha256']+suffix)
    _publish_immutable(root,original,raw_bytes,source['sha256'],'原件')
    references=current['items'] if isinstance(current,dict) else ()
    docpath,document_sha=_document_target(root,target,source['sha256'],document_raw,references)
    row={'id':('announcement-' if collection=='history' else 'import-')+source['sha256'][:24],
        'title':metadata['title'].strip(),'text':text,'url':metadata.get('url') or source['source_url'],
        'original_path':workspace_paths.store_path(root,original),'document_path':workspace_paths.store_path(root,docpath),
        'sha256':source['sha256'],'document_sha256':document_sha,'library_board':board,'layers':[board],
        'page_count':len(document['pages']),'text_completeness':document['text_completeness'],'as_of':str(date_today()),
        'kind':metadata.get('kind','unclassified'),'review_status':'original_bound_pending_professional_review'}
    if collection=='history':
        row.update(**history.extract_fields(text,metadata['title']),published_at=metadata.get('published_at'),
            publication_url=row['url'],publication_confirmed=metadata.get('publication_confirmed'),related_ids=metadata.get('related_ids',[]))
        applied=history.add(root,board,company,row,expected or history.state(root,board,company)['fingerprint'],actor)
        result={'id':row['id'],'status':'applied','fingerprint':applied['fingerprint'],'index':applied.get('index',{'status':'stale'})}
    else:
        if collection=='cases':row.update(source_kind='official_case',published_at=metadata.get('published_at',''),stock_code=metadata.get('stock_code',''),company=metadata.get('company_name',''),verification_status='official_original_indexed',eligible_as_case_evidence=False,case_admission_status='pending_publication_layer')
        elif collection=='blacklist_cases':
            values=lambda key:[x.strip() for x in str(metadata.get(key,'')).replace('，',',').split(',') if x.strip()]
            evidence={'id':'decision-'+source['sha256'][:20],'role':'regulatory_decision','title':metadata['title'].strip(),
                'url':row['url'],'published_at':metadata.get('published_at',''),'original_path':row['original_path'],
                'document_path':row['document_path'],'sha256':row['sha256'],'document_sha256':row['document_sha256'],'page_count':row['page_count']}
            row.update(company=metadata.get('company_name',''),stock_code=metadata.get('stock_code',''),authority=metadata.get('authority',''),
                decision_date=metadata.get('published_at',''),decision_number=metadata.get('decision_number',''),
                disposition_type=metadata.get('disposition_type',''),announcement_kinds=values('announcement_kinds'),
                violation_types=values('violation_types'),wrongdoing_summary=metadata.get('wrongdoing_summary',''),
                regulator_finding=metadata.get('regulator_finding',''),drafting_checks=values('drafting_checks'),
                evidence_documents=[evidence],admission_status='pending_review',verification_status='official_decision_pending_review',
                case_scope={'verified_board_at_misconduct':None})
        else:row.update(source_kind='official_rule',instrument_id=metadata.get('instrument_id') or row['id'],article=metadata.get('article') or '全文',effective_from=metadata.get('effective_from'),effective_to=metadata.get('effective_to'))
        old=library_admin.state(root,collection,board)
        duplicate=next((r for r in old['items'] if r.get('sha256')==row['sha256']),None)
        result={'status':'already_present','id':duplicate['id'],'fingerprint':old['fingerprint']} if duplicate else library_admin.update(root,collection,[row],expected or old['fingerprint'],board)
    source.update(status='applied',result=result)
    library_admin.atomic(_receipt_path(root,identity),history.encoded(source))
    return result


def date_today():
    from datetime import date
    return date.today()
