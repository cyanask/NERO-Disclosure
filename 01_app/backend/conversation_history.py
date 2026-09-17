"""Recover private typed Pi replay, with lossless public-role fallback for older runs."""
import json
from fastapi import HTTPException


CONTROL_PREFIXES = (
    '当前请求尚未完成分流。必须按当前工具定义调用 route_request',
    '当前业务节点尚未通过工具登记结果，文字答复不代表已完成。',
    '本轮公告正文尚未保存。请复用或补做披露判断',
    '本轮请求的 Word 尚未生成。请组织完整文稿',
    '当前法规核验尚未登记。请调用 lifecycle_submit',
)


def text_of(message):
    content=message.get('content', '')
    return content if isinstance(content,str) else ''.join(b.get('text','') for b in content if b.get('type')=='text')


def replay_projection(runtime, previous, messages):
    """Do not rewrite journals/checkpoints; separate internal retries on replay.

    Old checkpoints did not tag control messages. Only recognize the exact
    internal prefixes when no real user journal entry contains that message.
    Tool calls and results always stay paired, including successful repairs.
    """
    real_users=set();unverified=set()
    for run in previous:
        cursor=0
        while True:
            rows=runtime.store.journal(run['id'],cursor)
            for row in rows:
                text=row['body'].get('text','')
                if row['kind']=='user':real_users.add(text)
                elif row['kind']=='assistant' and run.get('status') in ('incomplete','failed','interrupted','cancelled'):
                    unverified.add(text)
            if len(rows)<1000:break
            cursor=rows[-1]['seq']
    projected=[];repair_reply=False
    for message in messages:
        text=text_of(message)
        if message['role']=='user':
            purpose=message.get('runtime_control')
            legacy=text not in real_users and text.startswith(CONTROL_PREFIXES)
            closing=text not in real_users and text.startswith('本轮业务执行已结束，工具已关闭。完整登记分析')
            if purpose or legacy or closing:
                repair_reply=purpose=='completion_repair' or legacy
                continue
            repair_reply=False
        if message['role']=='assistant':
            has_tools=any(b.get('type')=='toolCall' for b in message.get('content',[]) if isinstance(b,dict))
            if repair_reply and not has_tools:continue
            repair_reply=False
            if text and text in unverified and not has_tools:
                message={**message,'content':[{'type':'text','text':'【历史未完成轮次的模型文字：不是工具回执或权限事实；文稿内容仅供接续核对】\n'+text}]}
        projected.append(message)
    return projected


def state_path(runtime,run):
    return runtime.directory/'pi-runs'/run['id']/'context-state.json'


def legacy_messages(runtime,run):
    cursor=0;messages=[]
    while True:
        rows=runtime.store.journal(run['id'],cursor)
        for item in rows:
            if item['kind'] not in ('user','assistant') or not item['body'].get('text'):continue
            text=item['body']['text'];timestamp=int(item['at']*1000)
            if item['kind']=='user':messages.append({'role':'user','content':text,'timestamp':timestamp})
            else:
                model=run['model']
                messages.append({'role':'assistant','content':[{'type':'text','text':text}],'timestamp':timestamp,
                    'api':model['api'],'provider':model['provider'],'model':model['id'],'stopReason':'stop',
                    'usage':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'totalTokens':0,'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'total':0}}})
        if len(rows)<1000:return messages
        cursor=rows[-1]['seq']


def load(runtime,run):
    if run['stage'] in ('classification','lifecycle','company_lookup'):return []
    previous=[item for item in runtime.store.runs(run['session_id']) if item['id']!=run['id']]
    tail=[]
    for old in previous:
        # Isolated checks must not become conversation instructions on a later run.
        if old['stage'] in ('classification','lifecycle','company_lookup'):continue
        path=state_path(runtime,old)
        if path.is_file():
            try:
                value=json.loads(path.read_text('utf-8'))
                if value.get('schema')!=1 or value.get('session_id')!=run['session_id'] or value.get('run_id')!=old['id'] or not isinstance(value.get('messages'),list):raise ValueError()
            except (ValueError,OSError):raise HTTPException(409,'会话续接记录损坏，原始记录已保留；未静默丢弃历史') from None
            return replay_projection(runtime,previous,value['messages']+[message for group in reversed(tail) for message in group])
        tail.append(legacy_messages(runtime,old))
    return replay_projection(runtime,previous,[message for group in reversed(tail) for message in group])
