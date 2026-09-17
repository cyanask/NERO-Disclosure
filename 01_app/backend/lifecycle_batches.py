"""Manually started full-library law checks on the existing Pi runtime.

One regular Pi run per instrument, sequentially continued after settlement.
Batch metadata lives in the existing run journal; no second runtime or scheduler.
"""
from uuid import uuid5,NAMESPACE_URL
from fastapi import HTTPException
from . import law_lifecycle
from .chat_store import LIVE


def runs(runtime,identity):
    rows=[r for r in runtime.store.runs() if (r.get('lifecycle') or {}).get('batch_id')==identity]
    if not rows:raise HTTPException(404,'法规核验批次不存在')
    return sorted(rows,key=lambda r:r['created'])


def status(runtime,identity):
    rows=runs(runtime,identity);root=rows[0];targets=root['lifecycle']['targets'];byid={r['lifecycle']['instrument_id']:r for r in rows}
    items=[]
    for target in targets:
        run=byid.get(target['instrument_id']);result=(run or {}).get('lifecycle_result') or {}
        items.append({**target,'run_id':run['id'] if run else None,'status':run['status'] if run else 'pending',
                      'validity':result.get('validity','uncertain'),'result_status':result.get('status'),
                      'detail':result.get('detail') or (run or {}).get('reason','尚未开始')})
    completed=sum(r['status'] not in (*LIVE,'pending') for r in items)
    active=next((r for r in rows if r['status'] in LIVE),None)
    failure=any(r['status'] in ('failed','incomplete','interrupted','cancelled','blocked') or r['result_status']=='failed' for r in items)
    if active:state='cancelling' if root.get('lifecycle_stop') else 'running'
    elif root.get('lifecycle_stop'):state='cancelled'
    elif completed==len(items):state='partial' if failure else 'completed'
    elif root.get('lifecycle_error') or rows[-1]['status'] in ('interrupted','cancelled'):state='interrupted'
    else:state='running'
    return {'batch_id':identity,'status':state,'session_id':root['session_id'],'total':len(items),'completed':completed,
            'active_run_id':active['id'] if active else None,'items':items,'error':root.get('lifecycle_error'),
            'coverage_articles':sum(r['article_count'] for r in targets)}


def _next(runtime,root,position):
    batch=root['lifecycle'];target=batch['targets'][position]
    return runtime.accept(root['session_id'],{'text':'全库法规有效性核验：'+target['title'],
        'model_key':root['model']['key'],'stage':'lifecycle','request_id':str(uuid5(NAMESPACE_URL,batch['batch_id']+':'+target['instrument_id'])),
        'lifecycle':{**batch,'instrument_id':target['instrument_id'],'position':position}})


def start(runtime,board,model_key,request_id,ids=None):
    runtime.own()
    with runtime.lock:
        old=[r for r in runtime.store.runs() if (r.get('lifecycle') or {}).get('batch_id')==request_id]
        if old:
            root=min(old,key=lambda r:r['created'])
            if root['board']!=board or root['model']['key']!=model_key or root['lifecycle'].get('requested_ids')!=ids:
                raise HTTPException(409,'请求编号已用于不同核验范围')
            return status(runtime,request_id)
        if any(r['stage']=='lifecycle' and r['status'] in LIVE for r in runtime.store.runs(board=board)):
            raise HTTPException(409,'本板块已有法规核验运行，请等待完成或先停止')
        groups=law_lifecycle.instruments(runtime.root,board)
        selected=list(groups) if ids is None else ids
        if not selected or len(set(selected))!=len(selected) or set(selected)-groups.keys():raise HTTPException(422,'法规核验范围无效')
        targets=[{k:groups[i][k] for k in ('instrument_id','title','article_count')} for i in selected]
        session=runtime.store.create_session(board,None,'系统治理 · 法规核验',str(uuid5(NAMESPACE_URL,'law-governance:'+board)))
        first=runtime.accept(session['id'],{'text':'全库法规有效性核验：'+targets[0]['title'],'model_key':model_key,'stage':'lifecycle',
            'request_id':str(uuid5(NAMESPACE_URL,request_id+':'+targets[0]['instrument_id'])),
            'lifecycle':{'batch_id':request_id,'targets':targets,'requested_ids':ids,'instrument_id':targets[0]['instrument_id'],'position':0}})
        runtime.trace(first['id'],'lifecycle_batch_started',{'batch_id':request_id,'count':len(targets)})
        return status(runtime,request_id)


def settled(runtime,rid,stop):
    run=runtime.store.run(rid);batch=run.get('lifecycle') or {};identity=batch.get('batch_id')
    if not identity:return
    with runtime.lock:
        root=runs(runtime,identity)[0]
        if stop.is_set() or root.get('lifecycle_stop') or run['status'] in ('cancelled','interrupted'):return
        position=batch['position']+1
        if position>=len(batch['targets']):return
        try:
            model=runtime.settings.resolve_model(root['model']['key'])
            if any(model.get(k)!=root['model'].get(k) for k in ('provider','id','api','baseUrl','reasoning_effort')):
                raise HTTPException(409,'核验模型设置已变化，请重新发起批次')
            _next(runtime,root,position)
        except Exception as exc:
            runtime.store.update(root['id'],lifecycle_error=str(getattr(exc,'detail','后续核验未能启动'))[:1000])


def cancel(runtime,identity):
    with runtime.lock:
        rows=runs(runtime,identity);root=rows[0]
        runtime.store.update(root['id'],lifecycle_stop=True)
        for row in rows:
            if row['status'] in LIVE:runtime.cancel(row['id'])
        return status(runtime,identity)
