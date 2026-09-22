import json,time
from uuid import uuid4
from test_autonomous_control import control,send_auto
from test_pi_runtime import CONFIG,settled
from test_agent_tasks import candidate,plan_candidate,event
from test_open_intake import source_plan


def setup(c,r,mode='text'):
 r.config_override={**CONFIG,'workflow_policy':'continuous-v1'}
 from conftest import ready_layout
 if mode=='word':ready_layout(r.root)
 sample=event(c);body={k:sample[k] for k in ('company_id','kind','title','summary','facts')}
 body.update(workflow_policy='continuous-v1',output_mode=mode,request_id=str(uuid4()))
 if mode=='text':
  body.pop('company_id');body['facts']={k:v for k,v in body['facts'].items() if k!='disclosure_profile_id'}
  body.update(company_name='自动接续测试公司',board='chinext',kind='unclassified')
 e=c.post('/api/events',json=body).json()
 s=c.post('/api/chat/sessions',json={'event_id':e['id'],'board':'chinext','request_id':str(uuid4()),'title':'连续测试'}).json()
 return s,e


def runner_for(runtime,word=False):
 def runner(packet,emit,bridge,stop):
  emit({'type':'started'})
  if packet.get('stage')=='word':bridge('make_word',{});emit({'type':'done'});return
  result=bridge('route_request',{'domain':'disclosure','intent':'workflow','reason':'受控测试按明确请求制作正文'})
  assert result['next_context']['stage']=='assessment'
  result=bridge('submit_candidate',{'result':candidate()})
  assert result['next_context']['stage']=='plan'
  sid=packet['session_id'];run=runtime.store.runs(sid)[0]
  ctx=runtime.route('task.context',{'event_id':run['event_id'],'task_id':run['task_id']})
  plan=plan_candidate(ctx) if word else source_plan()
  result=bridge('submit_candidate',{'result':plan})
  if word:
   assert result['next_context']['stage']=='template'
   run=runtime.store.runs(sid)[0];ctx=runtime.route('task.context',{'event_id':run['event_id'],'task_id':run['task_id']})
   template=ctx['templates'][0];sections=template['sections'];mapping={req['requirement_id']:req['section_id'] for req in plan['requirements']}
   result=bridge('submit_candidate',{'result':{'template_id':template['id'],'requirement_map':mapping,'adaptations':['逐项承载当前正文要求']}})
   text='证券代码：000000 证券简称：模拟公司 主办券商：模拟券商 公告编号：模拟001\n# 董事会决议公告\n'+'\n'.join('## '+item['title']+'\n明确的模拟内容，供接口验收。' for item in plan['items'])
   draft={'template_id':template['id'],'text':text,'requirement_map':{x['requirement_id']:'明确的模拟内容，供接口验收。' for x in plan['requirements']}}
  else:
   draft={'documents':[{'document_id':d['document_id'],'text':d['title']+'\n本次事项涉及已列明的股东会程序。','requirement_map':{d['document_id']+'-fact':'本次事项涉及已列明的股东会程序。'}} for d in plan['documents']]}
  assert result['next_context']['stage']=='draft'
  result=bridge('submit_candidate',{'result':draft})
  assert result['terminate'] and result['data']['outcome']=='waiting_approval'
  emit({'type':'done'})
 return runner


def test_one_run_continues_text_to_real_human_gate(control):
 c,r,_=control;s,e=setup(c,r);r.runner=runner_for(r)
 out=settled(c,send_auto(c,s,'完成当前正文工作稿',expected_revision=e['revision']),timeout=60)
 assert out['run']['status']=='waiting_approval',out['run']
 saved=c.get('/api/events/'+e['id']).json()
 assert saved['stage']=='awaiting_draft_confirmation' and len(saved['draft']['documents'])==2
 assert not saved.get('approval_records')
 assert [x['body']['to'] for x in out['events'] if x['kind']=='stage_transition']==['plan','draft']


def test_word_after_human_confirmation_resumes_once_with_original_model(control):
 c,r,_=control;s,e=setup(c,r,'word');r.runner=runner_for(r,True)
 out=settled(c,send_auto(c,s,'完成Word工作稿，先确认正文',expected_revision=e['revision']),timeout=45)
 assert out['run']['status']=='waiting_approval',out['run']
 saved=c.get('/api/events/'+e['id']).json();assert saved['stage']=='awaiting_draft_confirmation'
 assert c.get('/api/events/'+e['id']+'/word/context').status_code==409
 gate=c.get('/api/events/'+e['id']+'/verify?stage=draft').json()
 payload={'stage':'draft','expected_revision':saved['revision'],'input_fingerprint':gate['input_fingerprint'],'decision':'accept','reviewer':'隔离工程验证','reason':'仅验证确认后的自动接续','content_review':'reviewed','request_id':str(uuid4())}
 confirmation=c.post('/api/events/'+e['id']+'/confirmations',json=payload);assert confirmation.status_code==200,confirmation.text
 continuation=confirmation.json()['continuation'];assert continuation['status']=='accepted',continuation
 rid=continuation['run_id'];deadline=time.monotonic()+15
 while r.store.run(rid)['status'] in ('accepted','running','cancelling') and time.monotonic()<deadline:time.sleep(.05)
 assert r.store.run(rid)['status']=='waiting_approval',r.store.run(rid)
 assert not any(x['kind'] in ('failure','script_failed') for x in r.store.journal(rid)),r.store.journal(rid)
 assert r.store.run(rid)['model']['key']==out['run']['model']['key']
 again=c.post('/api/events/'+e['id']+'/confirmations',json=payload);assert again.status_code==200,again.text
 assert len(r.store.runs(s['id']))==2
 saved=c.get('/api/events/'+e['id']).json();assert saved['stage']=='awaiting_word_confirmation'
 assert [x['node'] for x in saved['approval_records'] if x['state']=='current']==['draft']


def test_goal_stage_hint_does_not_poison_routing_revision(control):
 c,r,_=control;s,e=setup(c,r)
 def model(packet,emit,bridge,stop):
  routed=bridge('route_request',{'domain':'disclosure','intent':'workflow','stage':'draft','reason':'最终目标是正文，先执行当前合法节点'})
  assert routed['next_context']['stage']=='assessment'
  bridge('request_information',{'questions':['仅验证从正确节点结束']});emit({'type':'done'})
 r.runner=model;out=settled(c,send_auto(c,s,'起草正文',expected_revision=e['revision']))
 assert out['run']['stage']=='assessment' and out['run']['status']=='waiting_user'
 assert any(x['kind']=='stage_hint_corrected' for x in out['events'])


def test_queued_word_continuation_can_be_paused_before_parent_settles(control):
 import threading
 c,r,_=control;s,e=setup(c,r,'word');ready=threading.Event();release=threading.Event()
 base=runner_for(r,True)
 def held(packet,emit,bridge,stop):
  base(packet,emit,bridge,stop);ready.set()
  while not release.wait(.02) and not stop.is_set():pass
 r.runner=held
 response=send_auto(c,s,'测试排队接续暂停',expected_revision=e['revision']);assert response.status_code==200
 rid=response.json()['id'];assert ready.wait(45)
 try:
  saved=c.get('/api/events/'+e['id']).json();gate=c.get('/api/events/'+e['id']+'/verify?stage=draft').json()
  payload={'stage':'draft','expected_revision':saved['revision'],'input_fingerprint':gate['input_fingerprint'],'decision':'accept','reviewer':'隔离工程验证','reason':'测试排队暂停，不是人工验收','content_review':'reviewed','request_id':str(uuid4())}
  result=c.post('/api/events/'+e['id']+'/confirmations',json=payload);assert result.status_code==200,result.text
  assert result.json()['continuation']['status']=='queued'
  r.cancel(rid);release.set()
  deadline=time.monotonic()+10
  while r.store.run(rid)['status'] in ('accepted','running','cancelling') and time.monotonic()<deadline:time.sleep(.02)
  assert len(r.store.runs(s['id']))==1
  assert not r.store.run(rid).get('resume_after_settle')
  again=r.resume_after_confirmation(c.get('/api/events/'+e['id']).json())
  assert again['status']=='paused'
 finally:release.set()


def test_interrupted_model_wait_is_measured_separately(control):
 from fastapi import HTTPException
 c,r,_=control;s,e=setup(c,r)
 def interrupted(packet,emit,bridge,stop):
  emit({'type':'model_call_started','phase':'routing','reasoning_effort':'low','maxTokens':2048})
  time.sleep(.02)
  raise HTTPException(409,'隔离超时复现')
 r.runner=interrupted;out=settled(c,send_auto(c,s,'测试分项超时',expected_revision=e['revision']))
 assert out['run']['status']=='failed'
 assert out['run']['timings']['routing_ms']>=20
 assert out['run']['timings']['model_calls']==1
 assert any(x['kind']=='model_call_interrupted' for x in out['events'])


def test_done_receipt_with_idle_process_is_cleaned_without_false_failure(control,monkeypatch):
 import io,subprocess,threading
 c,r,_=control;s,e=setup(c,r)
 class IdleProcess:
  pid=12345;returncode=None
  def __init__(self,*args,**kwargs):self.stdin=io.StringIO();self.stdout=io.StringIO('{"type":"done"}\n');self.terminated=False
  def wait(self,timeout=None):
   if self.returncode is None:raise subprocess.TimeoutExpired('isolated worker',timeout)
   return self.returncode
  def poll(self):return self.returncode
  def terminate(self):self.terminated=True;self.returncode=-15
  def kill(self):self.returncode=-9
 process=IdleProcess();monkeypatch.setattr('backend.pi_runtime.subprocess.Popen',lambda *a,**k:process)
 r.runner=lambda packet,emit,bridge,stop:r.process(r.store.runs(s['id'])[0]['id'],packet,emit,bridge,stop)
 out=settled(c,send_auto(c,s,'只验证结束回执',expected_revision=e['revision']))
 assert out['run']['status']=='incomplete' # No business result, but not a transport failure.
 assert process.terminated
 assert any(x['kind']=='cleanup_fallback' for x in out['events'])
