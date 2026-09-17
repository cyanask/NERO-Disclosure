"""Read-only Office codec adapted from NERO Banker; see PROVENANCE.json."""
from __future__ import annotations

import posixpath
import re
import zipfile
from decimal import Decimal
from io import BytesIO
from typing import Any

from lxml import etree
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel

MAX_BYTES = 20 * 1024 * 1024
MAX_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 100
MAX_SECTIONS = 50
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
SPACE = '{http://www.w3.org/XML/1998/namespace}space'


class PlanDocumentError(ValueError):
    """Unsupported, unsafe or invalid plan document/coordinate."""


def _xml(data):
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    if root.getroottree().docinfo.doctype:
        raise PlanDocumentError('不支持含 DTD 的文档')
    return root


def _package(content, suffix):
    if suffix.lower().lstrip('.') not in ('xlsx', 'docx'):
        raise PlanDocumentError('仅支持 .xlsx 和 .docx 附件')
    if not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise PlanDocumentError('文档大小超限')
    try:
        archive = zipfile.ZipFile(BytesIO(content))
        infos = archive.infolist()
        if len(infos) > 2000 or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
            raise PlanDocumentError('文档解压大小或部件数量超限')
        if len({i.filename for i in infos}) != len(infos):
            raise PlanDocumentError('文档包含重复 ZIP 部件')
        parts = {i.filename: archive.read(i) for i in infos}
        return archive, parts
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise PlanDocumentError('无法读取 Office 文档包') from exc


def _size(rows, columns):
    if rows > MAX_ROWS or columns > MAX_COLUMNS:
        raise PlanDocumentError('计划行数或列数超限')


def _section(section_id, title, raw):
    header = next((i for i, row in enumerate(raw)
                   if sum(bool(c.strip()) for c in row['cells']) >= 2), None)
    if header is None:
        return dict(section_id=section_id, title=title, columns=[], rows=[],
                    warnings=['未找到至少两个非空单元格的标题行'], all_rows=raw)
    return dict(section_id=section_id, title=title, columns=raw[header]['cells'],
                rows=raw[header + 1:], warnings=['表头按首个至少两格非空行推定，请核对；无表头的分工说明页不适合直接录入。'],
                header_row_id=raw[header]['row_id'], all_rows=raw)



def _merge_projection(raw, merges):
    """Add display-only vertical context; horizontal spans never duplicate text."""
    for row in raw:
        row['effective_cells'] = list(row['cells'])
        row['merge_sources'] = []
        row['is_group'] = False
    for left, top, _right, bottom in merges:
        source = raw[top]
        for rn in range(top + 1, bottom + 1):
            row = raw[rn]
            if not row['cells'][left].strip():
                row['effective_cells'][left] = source['cells'][left]
                row['merge_sources'].append({
                    'column_index': left, 'source_row_id': source['row_id'],
                    'source_column_index': left,
                })
    for row in raw:
        row['merge_sources'].sort(key=lambda item: item['column_index'])
    for left, top, right, bottom in merges:
        source = raw[top]
        if (top == bottom and left == 0 and right > left
                and sum(bool(c.strip()) for c in source['effective_cells']) == 1
                and source['effective_cells'][left].strip()):
            source['is_group'] = True


def _docx_merges(raw, anchors):
    merges: list[list[int]] = []
    active: dict[tuple[int, int], list[int]] = {}
    for rn, row in enumerate(raw):
        following = {}
        for col in range(len(row['cells'])):
            tc = anchors.get((row['row_id'], col))
            if tc is None:
                continue
            span = tc.find('w:tcPr/w:gridSpan', NS)
            count = int(span.get(f"{{{NS['w']}}}val")) if span is not None else 1
            vertical = tc.find('w:tcPr/w:vMerge', NS)
            key = (col, count)
            if vertical is not None and vertical.get(f"{{{NS['w']}}}val") != 'restart':
                if key not in active:
                    raise PlanDocumentError('表格纵向合并缺少相邻原始锚点')
                active[key][3] = rn
                following[key] = active[key]
            elif vertical is not None or count > 1:
                bounds = [col, rn, col + count - 1, rn]
                merges.append(bounds)
                if vertical is not None:
                    following[key] = bounds
        active = following
    return merges


def _sheet_cells(root):
    cells = {}
    height = width = 0
    for row in root.findall('s:sheetData/s:row', NS):
        row_number = int(row.get('r', '0'))
        if row_number < 1:
            raise PlanDocumentError('工作表行坐标无效')
        height = max(height, row_number)
        for cell in row.findall('s:c', NS):
            ref = cell.get('r', '')
            if not re.fullmatch(r'[A-Z]+[1-9][0-9]*', ref):
                raise PlanDocumentError('单元格坐标无效')
            col, rn, _, _ = range_boundaries(ref)
            if rn != row_number or (rn, col) in cells:
                raise PlanDocumentError('单元格坐标重复或不一致')
            width = max(width, col)
            cells[rn, col] = cell
    merges = []
    protected = root.findall('s:mergeCells/s:mergeCell', NS) + root.xpath('.//s:f[@ref]', namespaces=NS)
    for merge in protected:
        bounds = range_boundaries(merge.get('ref'))
        merges.append(bounds)
        width, height = max(width, bounds[2]), max(height, bounds[3])
    _size(height, width)
    return cells, height, width, merges


def _cell_value(cell, strings, styles, epoch):
    formula_warning = False
    text = ''
    if cell is not None:
        v = cell.find('s:v', NS)
        text = v.text or '' if v is not None else ''
        kind = cell.get('t')
        formula = cell.find('s:f', NS) is not None
        if formula and not text:
            text = '[公式无缓存值]'
            formula_warning = True
        elif kind == 's' and text:
            text = strings[int(text)][0]
        elif kind == 'inlineStr':
            text = ''.join(cell.xpath('s:is//s:t/text()', namespaces=NS))
        elif kind == 'b' and text:
            text = 'TRUE' if text == '1' else 'FALSE'
        elif text and kind not in ('str', 'e', 'd'):
            style = int(cell.get('s', '0'))
            if style < len(styles):
                text = _number_display(text, styles[style], epoch)
        simple = (all(etree.QName(n).localname in ('v', 'is', 't') for n in cell.iterdescendants())
                  and (kind != 's' or strings[int(v.text)][1]))
    else:
        formula, simple = False, True
    return text, not formula and simple, formula_warning


def _percent_format(number_format):
    cleaned = re.sub(r'"[^"]*"|\\.', '', number_format.split(';')[0])
    return re.search(r'0(?:\.([0#]+))?%', cleaned)


def _number_display(text, number_format, epoch):
    percent = _percent_format(number_format)
    if percent:
        decimals = len(percent.group(1) or '')
        return f'{Decimal(text) * 100:.{decimals}f}%'
    if is_date_format(number_format):
        dt = from_excel(float(text), epoch)
        text = dt.isoformat(sep=' ') if hasattr(dt, 'date') else dt.isoformat()
        if text.endswith(' 00:00:00'):
            text = text[:-9]
    return text


def _xlsx_styles(parts):
    formats = dict(BUILTIN_FORMATS)
    styles = []
    if 'xl/styles.xml' in parts:
        root = _xml(parts['xl/styles.xml'])
        formats.update({int(n.get('numFmtId')): n.get('formatCode')
                        for n in root.findall('s:numFmts/s:numFmt', NS)})
        styles = [formats.get(int(n.get('numFmtId', '0')), '')
                  for n in root.findall('s:cellXfs/s:xf', NS)]
    return styles


def _xlsx(parts):
    workbook = _xml(parts['xl/workbook.xml'])
    rels = _xml(parts['xl/_rels/workbook.xml.rels'])
    targets = {r.get('Id'): r.get('Target') for r in rels if r.get('TargetMode') != 'External'}
    sheets = workbook.findall('s:sheets/s:sheet', NS)
    if len(sheets) > MAX_SECTIONS:
        raise PlanDocumentError('工作表数量超限')
    strings = []
    if 'xl/sharedStrings.xml' in parts:
        strings = [(''.join(si.xpath('.//s:t/text()', namespaces=NS)),
                    all(etree.QName(n).localname == 't' for n in si))
                   for si in _xml(parts['xl/sharedStrings.xml']).findall('s:si', NS)]
    styles = _xlsx_styles(parts)
    prop = workbook.find('s:workbookPr', NS)
    epoch = CALENDAR_MAC_1904 if prop is not None and prop.get('date1904') in ('1', 'true') else CALENDAR_WINDOWS_1900
    result = []
    total_cells = 0
    for sheet in sheets:
        target = targets.get(sheet.get(f"{{{NS['r']}}}id"), '')
        path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
        if not path.startswith('xl/') or path not in parts:
            raise PlanDocumentError('工作表关系无效')
        root = _xml(parts[path])
        cells, height, width, merges = _sheet_cells(root)
        total_cells += height * width
        if total_cells > 200000:
            raise PlanDocumentError("工作簿总单元格范围过大，请拆分文件后上传")
        raw = []
        formula_warning = False
        for rn in range(1, height + 1):
            values, editable, cell_metadata = [], [], []
            for col in range(1, width + 1):
                cell = cells.get((rn, col))
                merged = any(a <= col <= c and b <= rn <= d for a, b, c, d in merges)
                text, simple, missing = _cell_value(cell, strings, styles, epoch)
                formula_warning = formula_warning or missing
                values.append(text)
                cell_metadata.append({'coordinate': f'{get_column_letter(col)}{rn}',
                    'type': cell.get('t', 'n') if cell is not None else 'empty',
                    'number_format': styles[int(cell.get('s', '0'))] if cell is not None and int(cell.get('s', '0')) < len(styles) else 'General',
                    'raw_value': cell.findtext('s:v', namespaces=NS) if cell is not None else None,
                    'formula': cell.findtext('s:f', namespaces=NS) if cell is not None else None})
                if not merged and simple:
                    editable.append(col - 1)
            raw.append(dict(row_id=str(rn), cells=values, editable_columns=editable, cell_metadata=cell_metadata))
        actual_merges = [range_boundaries(m.get('ref'))
                         for m in root.findall('s:mergeCells/s:mergeCell', NS)]
        _merge_projection(raw, [(a - 1, b - 1, c - 1, d - 1) for a, b, c, d in actual_merges])
        section = _section('sheet:' + sheet.get('name'), sheet.get('name'), raw)
        section['merged_ranges'] = [m.get('ref') for m in root.findall('s:mergeCells/s:mergeCell', NS)]
        if formula_warning or root.find('.//s:f', NS) is not None:
            section['warnings'].append('公式仅显示文件保存时的缓存值，可能已过期；修改输入后需在 Excel 中重算。无缓存值时不计算')
        result.append((section, path, root, cells))
    return result


def _docx(parts, *, full=False):
    root = _xml(parts['word/document.xml'])
    tables = root.findall('w:body//w:tbl' if full else 'w:body/w:tbl', NS)
    if not tables and not full:
        raise PlanDocumentError('DOCX 没有可读取的顶层表格；暂不支持纯段落计划')
    if len(tables) > (500 if full else MAX_SECTIONS):
        raise PlanDocumentError('表格数量超限')
    result = []
    total_cells = 0
    for index, table in enumerate(tables):
        raw: list[dict[str, Any]] = []
        anchors = {}
        width = len(table.findall('w:tblGrid/w:gridCol', NS))
        trs = table.findall('w:tr', NS)
        _size(len(trs), width)
        revised = bool(table.xpath('.//w:ins | .//w:del | .//w:moveFrom | .//w:moveTo | .//*[contains(local-name(), "Change")]', namespaces=NS))
        for rn, tr in enumerate(trs):
            before = tr.find('w:trPr/w:gridBefore', NS)
            offset = int(before.get(f"{{{NS['w']}}}val")) if before is not None else 0
            _size(len(trs), offset)
            if offset < 0:
                raise PlanDocumentError('表格列坐标无效')
            values = [''] * offset
            editable = []
            for tc in tr.findall('w:tc', NS):
                col = len(values)
                span = tc.find('w:tcPr/w:gridSpan', NS)
                count = int(span.get(f"{{{NS['w']}}}val")) if span is not None else 1
                if count < 1 or count > MAX_COLUMNS:
                    raise PlanDocumentError('表格合并跨度无效或超限')
                values.append('\n'.join(''.join(p.xpath('.//w:t/text()', namespaces=NS))
                                        for p in tc.findall('w:p', NS)))
                values.extend([''] * (count - 1))
                anchors[str(rn), col] = tc
                allowed = {'tc', 'tcPr', 'p', 'pPr', 'r', 'rPr', 't'}
                # Property subtrees retain arbitrary formatting; content must be plain text.
                simple = all(etree.QName(n).localname in allowed for n in tc.iter()
                             if not any(etree.QName(a).localname in ('tcPr', 'pPr', 'rPr')
                                        for a in n.iterancestors() if a is not tc))
                if (simple and count == 1 and len(tc.findall('w:p', NS)) == 1
                        and tc.find('w:tcPr/w:vMerge', NS) is None
                        and tc.find('w:tcPr/w:hMerge', NS) is None
                        and not revised):
                    editable.append(col)
            width = max(width, len(values))
            _size(len(trs), width)
            raw.append(dict(row_id=str(rn), cells=values, editable_columns=editable))
        for row in raw:
            row['cells'].extend([''] * (width - len(row['cells'])))
        total_cells += len(raw) * width
        if total_cells > 200000:
            raise PlanDocumentError('Word表格总单元格范围过大，请按章节拆分附件')
        _merge_projection(raw, _docx_merges(raw, anchors))
        section = _section(f'table:{index}', f'表格 {index + 1}', raw)
        section['order'] = list(root.find('w:body', NS).iter()).index(table)
        result.append((section,
                       'word/document.xml', root, anchors))
    return result
