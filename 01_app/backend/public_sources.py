"""Public-only acquisition with original bytes and page-linked extraction."""
import hashlib,http.client,ipaddress,json,re,socket,ssl,subprocess,sys,time
from pathlib import Path
from urllib.parse import parse_qs,urlsplit,urljoin,urlencode,quote
from xml.etree import ElementTree
from html import unescape
from datetime import datetime,timezone
from fastapi import HTTPException
from .library_admin import atomic
from . import paths as workspace_paths
from .document_extract import TextParser, extract as extract_document

MAX_BYTES=20*1024*1024
SEARCH_ATTEMPTS=3
SEARCH_RETRY_PAUSE=1.5


def public_url(value):
    """Public acquisition policy, independent of source authority/admission."""
    if not isinstance(value,str) or any(ord(c)<32 for c in value):return False
    try:
        u=urlsplit(value)
        return bool(u.scheme=='https' and u.hostname and not u.username and not u.password and u.port in (None,443))
    except ValueError:return False


def candidate_url(value):
    """Search hits may be HTTP; acquisition still requires HTTPS at download time."""
    if not isinstance(value,str) or any(ord(c)<32 for c in value):return False
    try:
        u=urlsplit(value)
        return bool(u.scheme in ('http','https') and u.hostname and not u.username and not u.password and u.port in (None,80,443))
    except ValueError:return False


def public_addresses(host):
    addresses=list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
    synthetic=ipaddress.ip_network('198.18.0.0/15')
    if addresses and all(ipaddress.ip_address(x) in synthetic for x in addresses):
        # Resolve a public record through a fixed authenticated resolver; never dial a fake/private IP.
        resolver=http.client.HTTPSConnection('1.1.1.1',timeout=10)
        try:
            resolver.request('GET','/dns-query?'+urlencode({'name':host,'type':'A'}),headers={'accept':'application/dns-json'})
            response=resolver.getresponse();body=response.read(32000)
            if response.status!=200:raise HTTPException(409,'公开DNS解析暂不可用')
            value=json.loads(body)
            if value.get('Status')!=0:raise HTTPException(409,'未取得官方域名的公开解析记录')
            addresses=[x['data'] for x in value.get('Answer',[]) if x.get('type')==1]
        finally:resolver.close()
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):raise HTTPException(403,'公开下载不得连接本机或私有地址')
    return addresses


def fetch(url,search=False):
    for _ in range(5):
        if not public_url(url):
            raise HTTPException(422,'公开下载须为不含凭据的 HTTPS 地址，使用标准端口')
        u=urlsplit(url);host=(u.hostname or '').lower()
        addresses=public_addresses(host)
        connection=http.client.HTTPSConnection(host,timeout=20,context=ssl.create_default_context())
        try:
            # Pin the checked address while preserving TLS SNI and hostname verification.
            for address in addresses[:3]:
                raw_socket=None
                try:
                    raw_socket=socket.create_connection((address,443),timeout=10)
                    connection.sock=ssl.create_default_context().wrap_socket(raw_socket,server_hostname=host)
                    break
                except OSError:
                    if raw_socket:raw_socket.close()
            if connection.sock is None:raise OSError('No verified public endpoint connected')
            connection.request('GET',quote(u.path or '/',safe='/%:@+;=')+('?' +quote(u.query,safe='=&%:+,/?@') if u.query else ''),headers={'User-Agent':'NERO-Disclosure/1.0 public-research','Accept-Encoding':'identity'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):url=urljoin(url,response.getheader('Location',''));continue
            if response.status!=200:raise HTTPException(409,'公开来源返回 HTTP '+str(response.status))
            raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:raise HTTPException(413,'原件超过20MB，请分文件接纳')
            return raw,response.getheader('Content-Type',''),url
        except (OSError,TimeoutError,http.client.HTTPException) as exc:raise HTTPException(409,'公开来源暂时无法连接；未取得原件') from exc
        finally:connection.close()
    raise HTTPException(409,'公开来源重定向过多')


RESULT_ANCHOR=re.compile(r"<a\b[^>]*class=['\"](?:result-link|result__a)['\"][^>]*>(.*?)</a>",re.S)
RESULT_HREF=re.compile(r'href="([^"]+)"')
RESULT_SNIPPET=re.compile(r"<[^>]*class=['\"](?:result-snippet|result__snippet)['\"][^>]*>(.*?)</(?:a|td)>",re.S)
MARKUP=re.compile(r'<[^>]+>')


def plain_text(value):
    return re.sub(r'\s+',' ',unescape(MARKUP.sub('',value))).strip()


def result_target(link):
    """Unwrap a provider redirect; only the resolved public address is a candidate."""
    link=unescape(link)
    if link.startswith('//'):link='https:'+link
    parts=urlsplit(link);host=(parts.hostname or '').lower()
    if host=='duckduckgo.com' or host.endswith('.duckduckgo.com'):return (parse_qs(parts.query).get('uddg') or [''])[0]
    return link


def duckduckgo_search(query):
    """Primary channel; a throttled endpoint answers 202, so failed attempts are retried briefly."""
    url='https://lite.duckduckgo.com/lite/?'+urlencode({'q':query})
    for attempt in range(SEARCH_ATTEMPTS):
        try:
            raw,_,_=fetch(url,search=True);break
        except HTTPException:
            if attempt==SEARCH_ATTEMPTS-1:raise
            time.sleep(SEARCH_RETRY_PAUSE)
    page=raw.decode('utf-8',errors='replace');items=[];anchors=list(RESULT_ANCHOR.finditer(page))
    for index,anchor in enumerate(anchors):
        link=RESULT_HREF.search(anchor.group(0))
        target=result_target(link.group(1)) if link else ''
        if not candidate_url(target):continue
        # Keep each snippet inside its own result; a result without one must not borrow the next.
        limit=anchors[index+1].start() if index+1<len(anchors) else len(page)
        snippet=RESULT_SNIPPET.search(page,anchor.end(),limit)
        items.append({'title':plain_text(anchor.group(1)),'url':target,'snippet':plain_text(snippet.group(1)) if snippet else ''})
        if len(items)>=15:break
    return items


def bing_search(query):
    """Secondary channel; one provider returning nothing is a miss, not absence."""
    raw,_,_=fetch('https://www.bing.com/search?'+urlencode({'format':'rss','q':query}),search=True)
    tree=ElementTree.fromstring(raw)
    return [{'title':n.findtext('title'),'url':n.findtext('link'),'snippet':n.findtext('description')} for n in tree.findall('.//item') if candidate_url(n.findtext('link'))]


def search(query,board):
    if not isinstance(query,str) or not 1<=len(query.strip())<=300:raise HTTPException(422,'公开检索关键词无效')
    items=[];channel=''
    for name,collect in (('duckduckgo_html',duckduckgo_search),('bing_rss',bing_search)):
        try:candidates=collect(query)
        except (HTTPException,ElementTree.ParseError,OSError,UnicodeDecodeError):candidates=[]
        if candidates:items,channel=candidates,name;break
    if items:return {'items':items[:15],'board':board,'coverage':'公开搜索候选，尚未核对原件、版本及完整覆盖','query':query,'strategy':'public_search','channel':channel}
    # A search-provider miss is not absence. Supply freshly read official directory links,
    # explicitly labelled as navigation rather than law/case search hits.
    if board=='company_lookup':
        return {'items':[{'title':title,'url':url,'kind':'official_entry'} for title,url in (
            ('上海证券交易所','https://www.sse.com.cn/'),('深圳证券交易所','https://www.szse.cn/'),
            ('北京证券交易所','https://www.bse.cn/'),('全国股转系统','https://www.neeq.com.cn/'),
            ('巨潮资讯','https://www.cninfo.com.cn/'))], 'query':query,'board':board,
            'strategy':'official_navigation_fallback','coverage':'搜索未返回匹配结果；这些是官方入口，尚未核实公司归属。'}
    home='https://www.szse.cn/' if board=='chinext' else 'https://www.neeq.com.cn/'
    raw,_,final=fetch(home);parser=TextParser();parser.feed(raw.decode('utf-8',errors='replace'))
    seen=set();links=[]
    for item in parser.link_items:
        target=urljoin(final,item['url']);title=item['title'].strip()
        if public_url(target) and not urlsplit(target).hostname.startswith('biz.') and 'usepassword' not in target and target not in seen and re.search('规则|法规|公告|信息披露|业务指南|创业板',title):
            seen.add(target);links.append({'title':title,'url':target,'kind':'official_directory'})
    return {'items':links[:25] or [{'title':'官方公开网站入口','url':final,'kind':'official_entry'}],'board':board,'query':query,'strategy':'official_navigation_fallback',
            'coverage':'公开搜索没有提供可用结果。下列是本次读取的官方目录入口，不是匹配法规或案例；需继续读取目录定位原件，不能据此断言无更新。'}




def extract(path,output):
    raw=Path(path).read_bytes()
    if raw.startswith(b'%PDF-'):
        from pypdf import PdfReader
        reader=PdfReader(path)
        if reader.is_encrypted:raise ValueError('Encrypted PDF')
        pages=[{'page':i+1,'text':p.extract_text() or ''} for i,p in enumerate(reader.pages)];links=[]
    elif raw.startswith(b'PK'):
        import zipfile
        with zipfile.ZipFile(path) as archive:
            if 'word/document.xml' not in archive.namelist() or len(archive.infolist())>2000 or sum(x.file_size for x in archive.infolist())>30000000:
                raise ValueError('DOCX container unsupported')
        extracted=extract_document(path);pages=extracted['pages'];links=[]
    else:
        try:text=raw.decode('utf-8')
        except UnicodeDecodeError:text=raw.decode('gb18030',errors='replace')
        parser=TextParser();parser.feed(text)
        pages=[{'page':1,'text':re.sub(r'\n[ \t]*\n+', '\n\n',''.join(parser.parts))}];links=parser.links
    empty_pages=[p['page'] for p in pages if not p['text'].strip()]
    data={'pages':pages,'links':links,'extraction':'text_layer','empty_pages':empty_pages,
          'text_completeness':'text_layer_with_unread_or_blank_pages' if empty_pages else 'machine_extracted_text_layer',
          'requires_ocr':len(empty_pages)==len(pages)}
    Path(output).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')


def acquire(root,rid,board,url):
    root=Path(root);raw,content_type,final_url=fetch(url);digest=hashlib.sha256(raw).hexdigest()
    suffix='.pdf' if raw.startswith(b'%PDF-') else '.docx' if raw.startswith(b'PK') else '.html'
    if suffix=='.html' and 'html' not in content_type and not raw.lstrip().lower().startswith((b'<!doctype',b'<html')):raise HTTPException(422,'当前接纳 PDF 或 HTML 原件')
    batch=workspace_paths.work(root)/'downloads'/rid;batch.mkdir(parents=True,exist_ok=True)
    temporary=batch/(digest+suffix);atomic(temporary,raw)
    originals=workspace_paths.data(root)/'public/originals';originals.mkdir(parents=True,exist_ok=True)
    original=originals/(digest+suffix)
    if original.exists():
        if hashlib.sha256(original.read_bytes()).hexdigest()!=digest:raise HTTPException(409,'已有同名原件哈希冲突')
    else:atomic(original,raw)
    docroot=workspace_paths.data(root)/'public/extracted';docroot.mkdir(parents=True,exist_ok=True);document=docroot/(digest+'.json')
    registry=originals/'receipts';registry.mkdir(exist_ok=True)
    pending_receipt={'download_id':digest,'board':board,'url':url,'final_url':final_url,'sha256':digest,
        'original_path':workspace_paths.store_path(root,original),'document_path':workspace_paths.store_path(root,document),
        'retrieved_at':datetime.now(timezone.utc).isoformat(),'status':'downloaded_extraction_pending'}
    for receipt_path in (batch/(digest+'.json'),registry/(digest+'-'+board+'.json')):
        atomic(receipt_path,(json.dumps(pending_receipt,ensure_ascii=False,indent=2)+'\n').encode())
    if hashlib.sha256(temporary.read_bytes()).hexdigest()==digest:temporary.unlink()
    if not document.exists():
        pending=batch/(digest+'.extracted.json')
        try:
            subprocess.run([sys.executable,'-m','backend.public_sources',str(original),str(pending)],cwd=Path(__file__).resolve().parents[1],check=True,timeout=45,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError,OSError):raise HTTPException(409,'原件已留存，提取未完成；不得把它当作可引用正文')
        atomic(document,pending.read_bytes());pending.unlink()
    extracted=json.loads(document.read_text());receipt={'download_id':digest,'board':board,'url':url,'final_url':final_url,'sha256':digest,
        'original_path':workspace_paths.store_path(root,original),'document_path':workspace_paths.store_path(root,document),
        'document_sha256':hashlib.sha256(document.read_bytes()).hexdigest(),'retrieved_at':datetime.now(timezone.utc).isoformat(),
        'page_count':len(extracted['pages']),'requires_ocr':extracted['requires_ocr'],'empty_pages':extracted.get('empty_pages',[]),'text_completeness':extracted.get('text_completeness','not_verified'),'status':'downloaded_not_admitted'}
    atomic(batch/(digest+'.json'),(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode())
    registry=originals/'receipts';registry.mkdir(exist_ok=True)
    atomic(registry/(digest+'-'+board+'.json'),(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode())
    if temporary.exists() and hashlib.sha256(temporary.read_bytes()).hexdigest()==digest:temporary.unlink()
    return receipt


def receipt(root,rid,download_id):
    if not isinstance(download_id,str) or not re.fullmatch('[a-f0-9]{64}',download_id):raise HTTPException(422,'下载编号无效')
    path=workspace_paths.work(root)/'downloads'/rid/(download_id+'.json')
    if not path.is_file():raise HTTPException(404,'本轮没有这份已下载原件')
    value=json.loads(path.read_text());p=workspace_paths.resolve(root,value['original_path']);d=workspace_paths.resolve(root,value['document_path'])
    if not d.is_file() or not value.get('document_sha256'):raise HTTPException(409,'原件已保存，页级提取尚未完成')
    if hashlib.sha256(p.read_bytes()).hexdigest()!=value['sha256'] or hashlib.sha256(d.read_bytes()).hexdigest()!=value['document_sha256']:raise HTTPException(409,'原件或提取版本已变化')
    return value,json.loads(d.read_text())

if __name__=='__main__':
    if sys.platform!='win32':
        import resource
        if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(1024*1024*1024,1024*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU,(35,35))
    extract(sys.argv[1],sys.argv[2])
