"""Which registered knowledge, rules, templates and events reference given ids."""
from .domain import Seeds


def references(runtime,board,ids):
    selected=set(ids);seeds=Seeds(runtime.root).for_board(board);catalog=seeds.catalog();hits=[]
    def contains(v):
        if isinstance(v,str):return v in selected
        if isinstance(v,list):return any(contains(x) for x in v)
        if isinstance(v,dict):return any(contains(x) for x in v.values())
        return False
    for key in ('profiles','rules','templates'):
        hits += [{'kind':key,'title':r.get('title') or r.get('name') or r['id']} for r in catalog.get(key,[]) if contains(r)]
    for e in runtime.route('event.list',{'board':board}):
        if contains(e):hits.append({'kind':'直接引用事项','title':e['title']})
        elif e.get('verified_stages') or any(a.get('state')=='current' for a in e.get('approval_records',[])):
            hits.append({'kind':'知识版本变化后可能需复核','title':e['title']})
    return hits
