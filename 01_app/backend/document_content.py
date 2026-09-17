"""The saved draft text is canonical; this limited block model is derived from it."""
import re
class WordDeliveryError(ValueError):
    def __init__(self,status_code,detail):
        super().__init__(detail);self.status_code=status_code;self.detail=detail



def export_body(text,company_name,title):
    prefix=f'【演示稿／非正式披露文件】\n{company_name}\n{title}\n'
    return text[len(prefix):] if text.startswith(prefix) else text


def cells(line):
    return [c.strip().replace(r'\|','|') for c in re.split(r'(?<!\\)\|',line.strip().strip('|'))]


def required_header_fields(event):
    fields=['证券代码','证券简称','公告编号']
    if event.get('layer') in ('base','innovation'):
        fields.insert(2,'主办券商')
    return fields


def parse(event):
    text=export_body(event['draft']['text'],event['company_name'],event['title'])
    lines=text.replace('\r\n','\n').split('\n');blocks=[];i=0;title=None
    titles={x['title'] for x in event['plan']['items']}
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line:continue
        if line.startswith('```'):raise WordDeliveryError(422,'公告正文不支持代码块，请使用段落与表格')
        if line.startswith('|'):
            if i>=len(lines) or not all(re.fullmatch(r':?-{3,}:?',c) for c in cells(lines[i])):
                raise WordDeliveryError(422,'表格须有表头及---分隔行，不能静默按正文处理')
            header=cells(line);separator=cells(lines[i]);i+=1;rows=[]
            if len(separator)!=len(header) or not 1<=len(header)<=8:raise WordDeliveryError(422,'表格列数无效，最多8列')
            while i<len(lines) and lines[i].strip().startswith('|'):
                row=cells(lines[i]);i+=1
                if len(row)!=len(header):raise WordDeliveryError(422,'表格各行列数必须一致')
                if any(len(c)>2000 for c in row):raise WordDeliveryError(422,'表格单元格过长，请拆分内容')
                rows.append(row)
            if not rows or len(rows)>200:raise WordDeliveryError(422,'表格应有1至200行正文')
            blocks.append({'kind':'table','header':header,'rows':rows});continue
        heading=re.match(r'^(#{1,3})\s+(.+)$',line)
        if heading:
            value=heading.group(2)
            if not any(b['kind']!='meta' for b in blocks) and title is None and len(heading.group(1))==1 and value not in titles:
                title=value;continue
            blocks.append({'kind':'heading','level':min(len(heading.group(1)),2),'text':value});continue
        if line in titles or re.match(r'^[一二三四五六七八九十]+、',line):
            blocks.append({'kind':'heading','level':1,'text':line})
        elif re.match(r'^（[一二三四五六七八九十]+）',line):blocks.append({'kind':'heading','level':2,'text':line})
        elif any(re.search(word+r'[：:]',line) for word in ('证券代码','证券简称','主办券商','公告编号')):blocks.append({'kind':'meta','text':line})
        else:blocks.append({'kind':'paragraph','text':line})
    if not blocks:raise WordDeliveryError(422,'正文不能为空')
    return {'title':title or event['title'],'title_from_body':title is not None,'blocks':blocks}
