"""Bounded DOCX inspection and anchored manual-source edits; no business state."""
import io
import posixpath
from zipfile import ZipFile, BadZipFile
from lxml import etree
from fastapi import HTTPException

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def inspect(raw):
    if not 1 <= len(raw) <= 6_000_000:
        raise HTTPException(422, 'Word 文件须小于 6MB')
    try:
        with ZipFile(io.BytesIO(raw)) as z:
            infos = z.infolist()
            names = set(z.namelist())
            if len(infos) > 500 or len(infos) != len(names) or sum(i.file_size for i in infos) > 40_000_000:
                raise ValueError()
            if any(n.startswith('/') or '..' in n.split('/') or 'vbaProject' in n for n in names):
                raise ValueError()
            if z.testzip() is not None:
                raise ValueError()
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            roots = {n: etree.fromstring(z.read(n), parser) for n in names if n.endswith(('.xml', '.rels'))}
            content = roots['[Content_Types].xml']
            if not any(x.get('PartName') == '/word/document.xml' and x.get('ContentType') ==
                       'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml' for x in content):
                raise ValueError()
            if not any(x.get('Type', '').endswith('/officeDocument') and x.get('Target') == 'word/document.xml'
                       for x in roots['_rels/.rels']):
                raise ValueError()
            for name, root in roots.items():
                if not name.endswith('.rels'):
                    continue
                for relation in root:
                    if relation.get('TargetMode') == 'External':
                        continue
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(posixpath.dirname(name)),
                                                             relation.get('Target', ''))).lstrip('/')
                    if target not in names:
                        raise ValueError()
            root = roots['word/document.xml']
            if root.tag != '{' + W + '}document' or root.find('w:body', NS) is None:
                raise ValueError()
            blocks = [{'id': f'p{i}', 'text': ''.join(p.xpath('.//w:t/text()', namespaces=NS))}
                      for i, p in enumerate(root.findall('.//w:body//w:p', NS))]
            text = '\n'.join(b['text'] for b in blocks if b['text'])
            if not text.strip() or len(text) > 200_000:
                raise ValueError()
            return {'blocks': blocks, 'text': text, 'checks': ['zip_crc', 'xml_parse', 'opc_semantics', 'relationships', 'no_macros']}
    except (BadZipFile, KeyError, ValueError, etree.XMLSyntaxError, OSError):
        raise HTTPException(422, 'Word 文件结构无效、含宏或超过检查范围') from None


def patch(raw, edits):
    """Only explicit, unique body paragraph anchors change. Other ZIP parts stay byte-identical."""
    before = inspect(raw)
    if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
        raise HTTPException(422, '人工稿修改须提供 1 至 100 个明确锚点')
    seen = set()
    with ZipFile(io.BytesIO(raw)) as source:
        root = etree.fromstring(source.read('word/document.xml'), etree.XMLParser(resolve_entities=False, no_network=True))
        paragraphs = root.findall('.//w:body//w:p', NS)
        expected = [b['text'] for b in before['blocks']]
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {'block_id', 'original', 'replacement'}:
                raise HTTPException(422, '人工稿修改字段无效')
            key, old, new = edit['block_id'], edit['original'], edit['replacement']
            if key in seen or not isinstance(key, str) or not key.startswith('p') or not key[1:].isdigit():
                raise HTTPException(422, '每个修改锚点须唯一且来自当前人工稿')
            index = int(key[1:])
            if index >= len(paragraphs) or not isinstance(old, str) or not old or not isinstance(new, str) or len(new) > 10000:
                raise HTTPException(422, '人工稿修改锚点无效')
            if expected[index].count(old) != 1 or '\n' in new:
                raise HTTPException(409, '原文锚点不唯一、已变化或修改跨越段落，未改写人工稿')
            seen.add(key)
            start = expected[index].index(old)
            end = start + len(old)
            position = 0
            inserted = False
            for node in paragraphs[index].findall('.//w:t', NS):
                text = node.text or ''
                finish = position + len(text)
                if finish > start and position < end:
                    prefix = text[:max(0, start-position)]
                    suffix = text[max(0, end-position):] if finish > end else ''
                    node.text = prefix + (new if not inserted else '') + suffix
                    node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                    inserted = True
                position = finish
            expected[index] = expected[index].replace(old, new, 1)
        output = io.BytesIO()
        with ZipFile(output, 'w') as target:
            for info in source.infolist():
                target.writestr(info, etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                                if info.filename == 'word/document.xml' else source.read(info.filename))
    result = output.getvalue()
    after = inspect(result)
    if [b['text'] for b in after['blocks']] != expected:
        raise HTTPException(422, '人工稿修改回读不一致，未登记文件')
    return result, after
