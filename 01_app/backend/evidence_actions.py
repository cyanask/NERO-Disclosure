"""Describe observed requests without inventing a successful result."""
import json
from .evidence_access import access

NAMES={'laws':'法规库','cases':'案例库','blacklist_cases':'黑名单库','history':'历史公告库','templates':'模板库'}


def pending_actions(events, known):
    pending={}; calls={}; last={}
    def identify(name,args):
        args=args if isinstance(args,dict) else {}
        value=access(name,args,failed=True)
        if not value:return None
        identity=value.get('item_id');source=known.get(identity,{})
        category=value['category'] or source.get('category')
        if category not in NAMES:return None
        action='read' if identity else 'search'
        params={k:args[k] for k in ('query','page','view','offset') if k in args}
        key=json.dumps([category,action,identity,params],ensure_ascii=False,sort_keys=True)
        return key,{'category':category,'action':action,'identity':identity,'args':args,'source':source}
    for event in events:
        body=event['body'];kind=event['kind'];name=body.get('name','')
        if kind in ('model_tool_call','knowledge_requested','tool_requested'):
            item=identify(name,body.get('args',{}))
            if item:
                key,value=item;pending[key]=value;last[name]=key
                if body.get('id'):calls[body['id']]=key
        elif kind in ('tool_returned','knowledge_returned','tool_failed','model_tool_failed'):
            key=calls.get(body.get('id')) or last.get(name)
            if key:pending.pop(key,None)
        elif kind=='evidence_access':
            # New compact receipts carry the exact request; older ones resolve the
            # latest matching access only, never all requests in that category.
            request=body.get('request')
            if request:
                item=identify(body.get('tool',''),request)
                if item:pending.pop(item[0],None)
            else:
                for key,value in reversed(list(pending.items())):
                    if value['category']==body.get('category') and (not body.get('item_id') or value['identity']==body['item_id']):
                        pending.pop(key,None);break
    result={key:[] for key in NAMES}
    for value in pending.values():
        category=value['category'];args=value['args'];query=str(args.get('query','')).strip()
        if value['action']=='read':
            title=value['source'].get('title')
            text='已发起读取'+(f'《{title}》' if title else NAMES[category]+'中的指定资料')
            if args.get('page'):text+=f"第{args['page']}页"
        elif all(word in query for word in ('范围','数量','目录')):
            text='已发起查询'+NAMES[category]+'的可检索范围、数量及目录'
        elif args.get('view')=='groups':text='已发起查询'+NAMES[category]+'的分类目录'
        else:
            text='已发起查询'+NAMES[category]
            if query:text+='：'+(query[:160]+'…' if len(query)>160 else query)
        if text not in result[category]:result[category].append(text)
    return result
