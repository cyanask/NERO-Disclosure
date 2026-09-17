from uuid import uuid4
from test_autonomous_control import control,send_auto
from test_pi_runtime import settled
from backend.chat_store import question_title


def new(c,title='新会话'):
    return c.post('/api/chat/sessions',json={'board':'chinext','title':title,'request_id':str(uuid4())}).json()


def test_first_question_named_with_same_pi_route_and_retry(control):
    c,r,_=control;s=new(c)
    def model(p,emit,bridge,stop):
        assert '"session_title_needed": true' in p['system']
        assert p['tools'][0]['name']=='route_request'
        bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'咨询董事会披露','session_title':'董事会召开与披露安排'})
        emit({'type':'done'})
    r.runner=model
    request_id=str(uuid4());response=send_auto(c,s,'下个月要召开董事会',request_id=request_id)
    out=settled(c,response)
    detail=c.get('/api/chat/sessions/'+s['id']).json()
    assert detail['session']['title']=='董事会召开与披露安排'
    assert detail['event'] is None and out['run']['stage']=='chat'
    assert any(x['kind']=='session_named' for x in out['events'])
    retry=send_auto(c,s,'下个月要召开董事会',request_id=request_id)
    assert retry.json()['id']==response.json()['id']
    assert len(r.store.runs(s['id']))==1


def test_later_questions_and_manual_names_not_overwritten(control):
    c,r,_=control
    def model(p,emit,bridge,stop):
        bridge('route_request',{'domain':'disclosure','intent':'consult','reason':'信披咨询','session_title':'主控建议标题' if p['prompt']=='第一条披露问题' else '后续问题不得替换'})
        emit({'type':'done'})
    r.runner=model;s=new(c)
    settled(c,send_auto(c,s,'第一条披露问题'))
    settled(c,send_auto(c,s,'第二条披露问题'))
    assert c.get('/api/chat/sessions/'+s['id']).json()['session']['title']=='主控建议标题'
    assert c.patch('/api/chat/sessions/'+s['id'],json={'title':'人工整理标题'}).status_code==200
    settled(c,send_auto(c,s,'第三条披露问题'))
    assert c.get('/api/chat/sessions/'+s['id']).json()['session']['title']=='人工整理标题'
    custom=new(c,'用户指定的名称');settled(c,send_auto(c,custom))
    assert r.store.session(custom['id'])['title']=='用户指定的名称'


def test_fallback_and_existing_unnamed_sessions(control):
    c,r,_=control;s=new(c)
    def model(p,emit,bridge,stop):
        bridge('route_request',{'domain':'knowledge','intent':'query','reason':'知识库查询'})
        emit({'type':'done'})
    r.runner=model;out=settled(c,send_auto(c,s,'请帮我查询董事会相关规则'))
    assert r.store.session(s['id'])['title']=='查询董事会相关规则'
    assert out['run']['stage']=='knowledge'
    # Simulate an older unnamed record; listing derives its title without rewriting it.
    with r.store.connect() as db:db.execute("UPDATE sessions SET title='新会话' WHERE id=?",(s['id'],))
    assert c.get('/api/chat/sessions?board=chinext&q=董事会').json()[0]['title']=='查询董事会相关规则'
    with r.store.connect() as db:assert db.execute('SELECT title FROM sessions WHERE id=?',(s['id'],)).fetchone()[0]=='新会话'
    assert len(question_title('法规'*40))<=28


def test_manual_rename_cancels_pending_first_title(control):
    c,r,_=control;s=new(c)
    r.runner=lambda p,emit,bridge,stop:emit({'type':'done'})
    out=settled(c,send_auto(c,s,'董事会事项'))
    seed=r.store.session(s['id'])['title']
    assert c.patch('/api/chat/sessions/'+s['id'],json={'title':seed}).status_code==200
    assert not r.store.summarize_title(out['run']['id'],'不能覆盖的主控标题')
