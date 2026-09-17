"""Read-only DOCX/XLSX bytes adapter reused from NERO Banker."""

import hashlib

from .codec import NS, _docx, _package, _xlsx, _xml

READER_VERSION = 'banker-office-read-1'

def read_document_bytes(content, suffix):
    suffix = '.' + suffix.lower().lstrip('.')
    if not isinstance(content, bytes) or len(content) > 20 * 1024 * 1024:
        raise ValueError('文档大小超限，请使用分批读取入口。')
    archive, parts = _package(content, suffix)
    with archive:
        tables = _xlsx(parts) if suffix == '.xlsx' else _docx(parts, full=True)
        sections = []
        warnings = []
        for item in tables:
            section = dict(item[0])
            section['rows'] = section.pop('all_rows')
            warnings.extend(w for w in section['warnings'] if '表头' not in w and '标题行' not in w)
            sections.append(section)
        blocks = []
        if suffix == '.docx':
            blocks = _word_body(parts, sections, warnings)
        return {'reader_version': READER_VERSION, 'source_sha256': hashlib.sha256(content).hexdigest(),
                'sections': sections, 'blocks': blocks, 'warnings': warnings,
                'completeness': 'partial' if any('OCR' in w or '修订' in w or '未读取' in w for w in warnings) else 'complete'}

def _word_body(parts, sections, warnings):
    blocks = []
    root = _xml(parts['word/document.xml'])
    rows = []
    for number, node in enumerate(root.find('w:body', NS).iter()):
        if node.tag != f"{{{NS['w']}}}p" or any(p.tag == f"{{{NS['w']}}}tbl" for p in node.iterancestors()):
            continue
        text = ''.join(node.xpath('.//w:t/text()', namespaces=NS))
        if text.strip():
            row = {'row_id': f'P{number}', 'cells': [text], 'locator': f'paragraph:{number}', 'order': number}
            rows.append(row); blocks.append({'text': text, 'locator': row['locator'], 'order': number})
    if rows:
        sections.append({'section_id': 'body:paragraphs', 'title': '正文段落', 'columns': ['正文'], 'rows': rows, 'warnings': []})
    if root.findall('.//w:body//w:drawing', NS):
        warnings.append('文档含图片，图片文字尚未进行 OCR。')
    if root.findall('.//w:body//w:ins', NS) or root.findall('.//w:body//w:del', NS):
        warnings.append('文档包含修订；保留可读当前文字，需核对修订视图。')
    if any(name.startswith(('word/header','word/footer','word/footnotes','word/endnotes')) and name.endswith('.xml') and _xml(content).xpath('.//w:t/text()',namespaces=NS) for name,content in parts.items()):
        warnings.append('页眉页脚或脚注尾注文字未读取，请核对是否有需要补充的内容。')
    return blocks
