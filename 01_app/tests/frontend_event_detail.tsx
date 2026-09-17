import assert from 'node:assert/strict';
import {test} from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {currentEventStage,eventDetailState} from '../frontend/src/eventDetailView';
import DisclosureConfirmation,{DraftingSupplements} from '../frontend/src/components/DisclosureConfirmation';
import {canSubmitConfirmation} from '../frontend/src/humanGates';
import type {DisclosureEvent,Gate} from '../frontend/src/types';

const event={id:'one',revision:8,stage:'needs_reassessment',title:'测试事项',assessment:{summary:'已有判断',citations:[]},plan:null,draft:null,agent_tasks:[],approval_records:[]} as unknown as DisclosureEvent;
const gate:Gate={status:'PASS',stage:'assessment',input_fingerprint:'current',issues:[],next_action:{action:'human_review'},boundary:'本机检查边界'};
const blocked:Gate={...gate,status:'BLOCKED',issues:[{code:'method_changed',detail:'方法版本变化'},{code:'contract_version_missing',detail:'旧提交要求'}],next_action:{action:'notify_user_stop'}};

test('default stage follows business state and text output never enters Word',()=>{
 for(const [state,expected] of Object.entries({needs_reassessment:'assessment',awaiting_plan_confirmation:'plan',template_revision_required:'template',drafting:'draft',awaiting_draft_confirmation:'draft',awaiting_word_confirmation:'word',text_confirmed:'draft'}))assert.equal(currentEventStage({...event,stage:state}),expected);
 assert.equal(currentEventStage({...event,stage:'manual_escalation',escalation:{node:'plan',reason:'待处理'}}),'plan');
 assert.equal(currentEventStage({...event,output_mode:'text',stage:'confirmed_draft_archived'}),'draft');
});
test('outdated methods do not suggest a law-library repair',()=>{
 const view=eventDetailState(event,'assessment',blocked);
 assert.equal(view.title,'需要重新判断');assert.equal(view.outdated,true);assert.equal(view.lawProblem,false);assert.equal(view.canReview,true);
 assert.equal(eventDetailState(event,'assessment',{...blocked,issues:[{code:'law_missing',detail:'法源缺失'}]}).lawProblem,true);
});
test('only current fingerprint plus a passed check can show confirmed',()=>{
 const record={id:'approval',node:'assessment',state:'current',input_fingerprint:'old',reviewer:'复核人'};
 const e={...event,approval_records:[record]} as DisclosureEvent;
 assert.equal(eventDetailState(e,'assessment',gate).confirmed,undefined);
 record.input_fingerprint='current';assert.ok(eventDetailState(e,'assessment',gate).confirmed);
 assert.equal(eventDetailState(e,'assessment',blocked).confirmed,undefined);
});
test('pending semantic review and automatic-only stages never look confirmed',()=>{
 const pending=eventDetailState(event,'assessment',{...gate,status:'PENDING_REVIEW',next_action:{action:'semantic_review'}});
 assert.equal(pending.title,'需要专业复核');assert.equal(pending.needsConfirmation,false);
 assert.equal(eventDetailState({...event,workflow_policy:'continuous-v1',stage:'assessed'},'assessment',{...gate,next_action:{action:'advance'}}).needsConfirmation,false);
});
test('live tasks take priority and unadopted candidates remain distinguishable',()=>{
 const task={id:'task',stage:'assessment',status:'pending',created_at:1,result:{summary:'候选'}};
 const e={...event,agent_tasks:[task]} as DisclosureEvent;
 assert.equal(eventDetailState(e,'assessment',blocked).canReview,false);
 const v=eventDetailState({...e,assessment:null,agent_tasks:[{...task,status:'submitted'}]} as DisclosureEvent,'assessment',blocked);
 assert.equal(v.result,null);assert.equal(v.candidate?.id,'task');assert.equal(v.canReview,false);
});
test('detail confirmation entry says return for revision while preserving rejection gates',()=>{
 const html=renderToStaticMarkup(<DisclosureConfirmation event={event} stage="assessment" gate={blocked} busy={false} write={async()=>false} compact presentation="detail"/>);
 assert.match(html,/查看问题并退回修订/);assert.doesNotMatch(html,/审阅并确认当前/);
 const fields={stage:'assessment',reviewer:'复核人',reason:'需要修订',gate:blocked,content:false,visual:false};
 assert.equal(canSubmitConfirmation({...fields,decision:'reject'}),true);
 assert.equal(canSubmitConfirmation({...fields,decision:'prepare_mandatory'}),false);
 assert.equal(canSubmitConfirmation({...fields,decision:'reject',reason:''}),false);
 const ready=renderToStaticMarkup(<DisclosureConfirmation event={event} stage="assessment" gate={gate} busy={false} write={async()=>false} compact presentation="detail"/>);
 assert.match(ready,/审阅并确认当前结果/);
});
test('special handling keeps a human decision and unsupported stages never offer confirmations',()=>{
 const special={...gate,next_action:{action:'manual_escalation'}};
 const view=eventDetailState({...event,workflow_policy:'continuous-v1',stage:'manual_escalation'},'assessment',special);
 assert.equal(view.title,'需要人工专项处理');assert.equal(view.needsConfirmation,true);
 assert.match(renderToStaticMarkup(<DisclosureConfirmation event={event} stage="assessment" gate={special} busy={false} write={async()=>false} compact presentation="detail"/>),/审阅专项处理决定/);
 for(const stage of ['plan','template']){
  const e={...event,workflow_policy:'continuous-v1',plan:{items:[]},template:{adaptations:[]}} as unknown as DisclosureEvent;
  assert.equal(eventDetailState(e,stage,blocked).canReview,false);
 }
 assert.equal(eventDetailState({...event,draft:{text:'正文'}} as DisclosureEvent,'draft',blocked).canReview,false);
});
test('historical tasks are not current candidates and supplement controls remain independent',()=>{
 for(const status of ['stale','cancelled','failed','adopted']){
  const e={...event,assessment:null,agent_tasks:[{id:'old',stage:'assessment',status,created_at:1,result:{summary:'旧记录'}}]} as DisclosureEvent;
  assert.equal(eventDetailState(e,'assessment',blocked).candidate,undefined);
 }
 const e={...event,workflow_policy:'continuous-v1',plan:{drafting_gaps:[{key:'date',description:'补日期',impact:'draft',treatment:'supply'}]}} as unknown as DisclosureEvent;
 const html=renderToStaticMarkup(<DraftingSupplements event={e} stage="template" busy={false} write={async()=>false}/>);
 assert.match(html,/补充已列明的制稿资料/);assert.match(html,/保存制稿补充/);
});
