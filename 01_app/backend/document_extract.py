"""Official-document parsing: PDF page blocks, text layer, OCR fallback and DOCX blocks."""
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from html.parser import HTMLParser
from fastapi import HTTPException


class TextParser(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.parts=[];self.links=[];self.link_items=[];self.active_link=None
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):self.skip+=1
        if tag in ('p','div','br','li','tr','h1','h2','h3'):self.parts.append('\n')
        if tag=='a':
            link=dict(attrs).get('href')
            if link:self.links.append(link);self.active_link={'url':link,'title':''}
    def handle_endtag(self,tag):
        if tag=='a' and self.active_link:self.link_items.append(self.active_link);self.active_link=None
        if tag in ('script','style','noscript'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)
        if self.active_link:self.active_link['title']+=data



def packaged_ocr():
    helper=Path(__file__).resolve().parents[1]/'runtime/macos/bin/disclosure-ocr'
    return helper if sys.platform=='darwin' and helper.is_file() else None


def native_ocr(arguments):
    result=subprocess.run([str(packaged_ocr()),*map(str,arguments)],capture_output=True,text=True,timeout=120,check=True)
    rows=json.loads(result.stdout)
    return {'text':'\n'.join(x['text'] for x in rows),'engine':'apple_vision','lines':rows,'review_required':True}


def ocr(image):
    if packaged_ocr():return native_ocr([image])
    executable=shutil.which('tesseract')
    if executable:
        langs=subprocess.run([executable,'--list-langs'],capture_output=True,text=True,timeout=10).stdout
        language='chi_sim+eng' if 'chi_sim' in langs else 'eng'
        result=subprocess.run([executable,str(image),'stdout','-l',language],capture_output=True,text=True,timeout=90,check=True)
        return {'text':result.stdout,'engine':'tesseract','review_required':True}
    if sys.platform=='darwin' and shutil.which('swift'):
        script=Path(__file__).resolve().parents[1]/'scripts/ocr_image.swift'
        cache=Path(tempfile.gettempdir())/'nero-disclosure-ocr-module-cache';cache.mkdir(exist_ok=True)
        result=subprocess.run(['swift','-module-cache-path',str(cache),str(script),str(image)],capture_output=True,text=True,timeout=120,check=True)
        rows=json.loads(result.stdout)
        return {'text':'\n'.join(x['text'] for x in rows),'engine':'apple_vision','lines':rows,'review_required':True}
    return {'text':'','engine':'unavailable','review_required':True}


def pdf_blocks(text,page):
    blocks=[];table=[]
    def flush():
        if table:blocks.append({'type':'table_candidate','anchor':f'page:{page}:table:{len(blocks)+1}','rows':list(table),'review_required':True});table.clear()
    for n,line in enumerate(text.splitlines(),1):
        if not line.strip():flush();continue
        cells=re.split(r'\s{2,}',line.strip())
        if len(cells)>1:table.append(cells);continue
        flush();blocks.append({'type':'heading' if re.match(r'^(?:[一二三四五六七八九十]+、|第.+[章节])',line.strip()) else 'paragraph','anchor':f'page:{page}:line:{n}','text':line.strip()})
    flush();return blocks


def extract(path):
    """Preserve Word block order and PDF page anchors; OCR does not assert fidelity."""
    path=Path(path);raw=path.read_bytes();pages=[];blocks=[];warnings=[]
    if raw.startswith(b'%PDF-'):
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:raise HTTPException(422,'请上传未加密 PDF')
        with tempfile.TemporaryDirectory(prefix='disclosure-ocr-') as tmp:
            for index,page in enumerate(reader.pages,1):
                try:text=page.extract_text(extraction_mode='layout') or ''
                except (KeyError,ValueError):text=page.extract_text() or ''
                entry={'page':index,'text':text,'method':'text_layer','anchor':f'page:{index}'}
                # Sparse text or embedded images need inspection even if headers extracted.
                resources=page.get('/Resources',{})
                if hasattr(resources,'get_object'):resources=resources.get_object()
                images=bool(resources.get('/XObject'))
                if len(re.sub(r'\s','',text))<40:
                    if packaged_ocr():
                        try:result=native_ocr(['--pdf-page',path,index])
                        except (subprocess.SubprocessError,ValueError):result={'text':'','engine':'failed','review_required':True}
                        entry.update(text=result['text'] or text,method=result['engine'],ocr=result)
                    elif shutil.which('pdftoppm'):
                        target=Path(tmp)/f'page-{index}'
                        subprocess.run(['pdftoppm','-f',str(index),'-l',str(index),'-r','150','-singlefile','-png',str(path),str(target)],capture_output=True,check=True,timeout=60)
                        try:result=ocr(target.with_suffix('.png'))
                        except (subprocess.SubprocessError,ValueError):result={'text':'','engine':'failed','review_required':True}
                        entry.update(text=result['text'] or text,method=result['engine'],ocr=result)
                    if not entry['text'].strip():warnings.append(f'第 {index} 页无可读正文，需 OCR 或人工补核')
                elif images:entry['image_review_required']=True
                entry['blocks']=pdf_blocks(entry['text'],index)
                if any(b['type']=='table_candidate' for b in entry['blocks']):entry['table_review_required']=True
                pages.append(entry)
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist())>150*1024*1024:raise HTTPException(422,'Word 解压后过大')
            if 'word/document.xml' not in archive.namelist():raise HTTPException(422,'请上传 DOCX 格式 Word')
            if any('vbaProject' in n for n in archive.namelist()):raise HTTPException(422,'不接纳含宏文件')
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        document=Document(path)
        for i,child in enumerate(document.element.body,1):
            if child.tag.endswith('}p'):
                paragraph=Paragraph(child,document)
                blocks.append({'anchor':f'body:{i}','type':'paragraph','style':paragraph.style.name,'text':paragraph.text})
            elif child.tag.endswith('}tbl'):
                table=Table(child,document);rows=[[c.text for c in row.cells] for row in table.rows]
                blocks.append({'anchor':f'body:{i}','type':'table','rows':rows,'text':'\n'.join('\t'.join(row) for row in rows)})
        for section_index,section in enumerate(document.sections,1):
            for label,part in (('header',section.header),('footer',section.footer)):
                for i,p in enumerate(part.paragraphs,1):
                    if p.text:blocks.append({'anchor':f'{label}:{section_index}:{i}','type':label,'text':p.text})
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix='disclosure-word-ocr-') as tmp:
            import xml.etree.ElementTree as ET
            for part in ('word/footnotes.xml','word/endnotes.xml'):
                if part in archive.namelist():
                    for note in ET.fromstring(archive.read(part)):
                        content='\n'.join(''.join(p.itertext()) for p in note.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
                        if content.strip():blocks.append({'anchor':part+':'+str(note.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')),'type':'note','text':content})
            for member in archive.namelist():
                if member.startswith('word/media/') and member.lower().endswith(('.png','.jpg','.jpeg','.tif','.tiff','.bmp')):
                    image=Path(tmp)/Path(member).name;image.write_bytes(archive.read(member))
                    try:result=ocr(image)
                    except (subprocess.SubprocessError,ValueError):result={'text':'','engine':'failed'}
                    blocks.append({'anchor':member,'type':'image_ocr',**result})
            xml=archive.read('word/document.xml')
            if b'<w:del' in xml or b'<w:ins' in xml:warnings.append('Word 含修订记录，当前抽取不得视为人工定稿')
            if b'txbxContent' in xml:warnings.append('Word 含文本框，请结合原件核对阅读顺序')
        pages=[{'page':1,'text':'\n'.join(b['text'] for b in blocks),'method':'docx_structure','blocks':blocks,'anchor':'document','page_label':'Word 结构段落（非排版页码）'}]
    elif raw.lstrip().lower().startswith((b'<!doctype',b'<html')):
        try:text=raw.decode('utf-8')
        except UnicodeDecodeError:text=raw.decode('gb18030',errors='replace')
        parser=TextParser();parser.feed(text)
        body=re.sub(r'\n[ \t]*\n+','\n\n',''.join(parser.parts)).strip()
        pages=[{'page':1,'text':body,'method':'official_html','blocks':pdf_blocks(body,1),'anchor':'page:1'}]
    else:
        raise HTTPException(422,'支持 PDF、DOCX 和官方 HTML；旧版 .doc 请先另存为 DOCX')
    needs_review=bool(warnings) or any(p.get('ocr') or p.get('image_review_required') or p.get('table_review_required') for p in pages) or any(b['type']=='image_ocr' for b in blocks)
    return {'pages':pages,'warnings':warnings,'needs_review':needs_review,'text_completeness':'machine_extracted_pending_review' if needs_review else 'machine_extracted',
        'requires_ocr':any(not p['text'].strip() for p in pages)}

