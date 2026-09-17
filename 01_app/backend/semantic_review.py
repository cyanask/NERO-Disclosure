"""Independent semantic review: fresh context, read-only, version-bound verdicts.

Deterministic checks stay in disclosure_contract/gates. This module only carries
the evidence packet, the reviewer prompt, bounded result parsing and the reuse
cache. It never edits facts, laws or candidates and never resolves a Gate.
"""
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

RULE_VERSION='semantic-review-v1'
MAX_ITEMS=40
CACHE_LIMIT=500

SYSTEM=(
 '你是独立的事实一致性复核员，只回答“结构化事实值是否被给出的原文引文支持”。\n'
 '判断标准：主体、期间、数值、单位、否定词、条件和范围均未改变才可判 supported；\n'
 '数字或金额不等、单位换算不同、否定词变化、主体或期间变化判 conflict；原文不足以判断判 insufficient。\n'
 '格式化差异不算矛盾：千分位、全角半角、日期写法（2026年9月1日 / 2026-09-01）、括注位置（未经审计 / （未经审计））只要含义一致即为 supported。\n'
 '只依据给出的引文和上下文，不使用你的记忆或外部知识，不改写事实，不给出法律结论。\n'
 '严格只输出一个 JSON 对象，形如 {"verdicts":[{"item_id":"...","verdict":"supported|conflict|insufficient","reason":"简短理由","locator":"原文位置"}]}，\n'
 '每个 item 恰好一条结论，不输出 JSON 以外的任何文字或代码块标记。'
)


def items_digest(items):
    """Reuse key: candidate-bound evidence and the deployed review rule version."""
    bound=[{'item_id':row.get('item_id'),'value':row.get('value'),'quote':row.get('quote'),
            'source_ref':row.get('source_ref'),'evidence_sha':row.get('evidence_sha'),
            'rule':RULE_VERSION} for row in items]
    return hashlib.sha256(json.dumps(bound,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def prompt(items):
    payload=[{'item_id':row.get('item_id'),'fact_key':row.get('fact_key'),'结构化事实值':row.get('value'),
              '原文引文':row.get('quote'),'来源':row.get('source_ref'),'原文上下文':row.get('context')} for row in items]
    return ('请逐项复核下列事实与原件的对应关系，并按系统要求只输出 JSON：\n'+
            json.dumps({'items':payload},ensure_ascii=False))


def _load(path):
    try:value=json.loads(path.read_text('utf-8'))
    except (OSError,ValueError):return {}
    return value if isinstance(value,dict) else {}


def lookup(directory,key):
    row=_load(Path(directory)/'semantic-reviews.json').get(key)
    verdicts=row.get('verdicts') if isinstance(row,dict) else None
    return verdicts if isinstance(verdicts,list) else None


def store(directory,key,verdicts):
    path=Path(directory)/'semantic-reviews.json'
    data=_load(path)
    data[key]={'at':time.time(),'rule':RULE_VERSION,'verdicts':verdicts}
    if len(data)>CACHE_LIMIT:
        keep=sorted(data.items(),key=lambda item:item[1].get('at',0))[-CACHE_LIMIT:]
        data=dict(keep)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid4().hex[:8]+'.next')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,path)


def parse(text, items):
    """Return per-item verdicts, or None when the reviewer output is unusable."""
    raw=str(text or '').strip()
    if raw.startswith('```'):raw=raw.strip('`').removeprefix('json').strip()
    start,end=raw.find('{'),raw.rfind('}')
    if start<0 or end<=start:return None
    try:value=json.loads(raw[start:end+1])
    except ValueError:return None
    rows=value.get('verdicts') if isinstance(value,dict) else None
    if not isinstance(rows,list):return None
    known={row['item_id'] for row in items}
    out=[]
    for row in rows[:MAX_ITEMS]:
        if not isinstance(row,dict) or row.get('item_id') not in known:continue
        verdict=row.get('verdict')
        if verdict not in ('supported','conflict','insufficient'):continue
        reason=str(row.get('reason') or '').strip() or '未提供理由'
        out.append({'item_id':row['item_id'],'verdict':verdict,'reason':reason[:2000],
                    'locator':str(row.get('locator') or '')[:300]})
    return out
