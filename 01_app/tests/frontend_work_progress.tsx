import assert from 'node:assert/strict';
import {test} from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {workActivities,workProgress,eventRefreshSequence} from '../frontend/src/workProgress';
import WorkProgress from '../frontend/src/components/WorkProgress';
import type {PiRun,Receipt} from '../frontend/src/chat';
const run={id:'r',session_id:'s',event_id:'conversation:s',stage:'chat',status:'running',created:1} as PiRun;
const row=(seq:number,kind:string,body:object,run_id='r')=>({seq,kind,body,run_id,at:1} as Receipt);
const call=(id:string,name='knowledge_read')=>({id,name,transport:'pi_model'});
test('all task types have the same live/queued/disconnected/history contract',()=>{
 for(const stage of ['chat','knowledge','announcement','document','assessment','scope']){
  const r={...run,stage};assert.equal(workProgress(r).animate,true);
  assert.equal(workProgress({...r,status:'accepted'}).animate,false);
  assert.match(workProgress({...r,status:'accepted'}).title,/等待启动/);
  const off=workProgress(r,[],{disconnected:true});assert.equal(off.animate,false);assert.match(off.title,/状态待同步/);
  const old=workProgress(r,[],{historical:true});assert.equal(old.animate,false);assert.equal(old.action,undefined);
 }
});
test('duplicate receipts, retry IDs, out-of-order reads and other runs cannot mix',()=>{
 const rows=[row(4,'tool_started',call('second')),row(2,'tool_started',call('first')),row(3,'tool_failed',{...call('first'),error:'读取失败'}),row(4,'tool_started',call('second')),row(5,'tool_returned',call('second'),'another')];
 const items=workActivities(run,rows);assert.equal(items.length,2);assert.equal(items[0].state,'failed');assert.equal(items[1].state,'running');
 const complete=workActivities(run,[...rows,row(6,'tool_returned',call('second'))]);assert.deepEqual(complete.map(i=>i.state),['failed','done']);
});
test('older name-only observations do not imply pairing or completion',()=>{
 const rows=[row(1,'knowledge_requested',{name:'knowledge_read'}),row(2,'knowledge_requested',{name:'knowledge_read'}),row(3,'knowledge_returned',{name:'knowledge_read'})];
 assert.deepEqual(workActivities(run,rows).map(i=>i.state),['requested','requested','done']);
 assert.deepEqual(workProgress({...run,status:'completed'},rows).activities.map(i=>i.state),['unknown','unknown','done']);
});
test('canonical model operations suppress duplicate internal operations and preserve business results',()=>{
 const items=workActivities(run,[row(1,'tool_started',call('p')),row(2,'tool_started',{id:'inner',name:'event.get'}),row(3,'tool_returned',{id:'inner',name:'event.get'}),row(4,'tool_returned',call('p')),row(5,'knowledge_proposal',{summary:'修改法规版本'})]);
 assert.equal(items.length,2);assert.equal(items[0].state,'done');assert.equal(items[1].state,'done');
 assert.doesNotMatch(JSON.stringify(items),/变更已执行/);
});
test('request registration, unknown tools and model text do not invent completed work',()=>{
 const rows=[row(1,'tool_requested',call('one','arbitrary_new_tool')),row(2,'assistant',{text:'全部核验通过，已生成Word'}),row(3,'verification',{status:'PENDING_REVIEW'})];
 const p=workProgress(run,rows);assert.doesNotMatch(p.title,/正在处理资料|已生成/);assert.equal(p.activities[0].state,'requested');assert.equal(p.activities[1].state,'unknown');assert.equal(p.action,undefined);
});
test('awaiting input and knowledge preview are real handoffs, not ongoing work',()=>{
 const p=workProgress({...run,status:'waiting_user',questions:['请确认金额口径']});assert.equal(p.action,'input');assert.equal(p.animate,false);
 const k=workProgress({...run,stage:'knowledge',status:'waiting_knowledge_confirmation',knowledge_change:{summary:'指定条目拟修改'} as never});assert.equal(k.action,'knowledge');assert.equal(k.animate,false);assert.match(k.title,/待确认/);
 const review=workProgress({...run,status:'waiting_approval'},[],{pendingReview:'正文确认'});assert.equal(review.action,'review');
});
test('completion, failed closing, cancellation and artifacts retain separate meanings',()=>{
 const rows=[row(1,'documents_created',{documents:[{title:'公告工作稿',version:2}]})];
 const done=workProgress({...run,stage:'document',status:'completed',finalization_status:'failed'},rows);assert.match(done.title,/已生成/);assert.match(done.detail,/收尾答复未完成/);assert.match(done.detail,/审阅/);
 for(const status of ['failed','interrupted','blocked','incomplete','cancelled','cancelling']){
  const p=workProgress({...run,status},[row(1,'tool_started',call('one'))]);assert.equal(p.animate,false);assert.equal(p.activities[0].state,'unknown');
 }
 const failed=workProgress({...run,status:'failed'},rows);assert.equal(failed.action,'documents');assert.match(failed.detail,/已有文件登记/);
});
test('pure query terminates without announcement steps; historical graph is absent',()=>{
 const current={...run,status:'completed'},p=workProgress(current);
 assert.equal(p.action,undefined);
 const html=renderToStaticMarkup(<WorkProgress progress={p} run={current} runs={[current]} open onOpen={()=>{}} onSelect={()=>{}} onAction={()=>{}} onEvidence={()=>{}} onCurrent={()=>{}}/>);
 assert.doesNotMatch(html,/Gate|披露判断|模板适配|<svg|graph-/);assert.match(html,/查看本轮依据/);
 const empty=renderToStaticMarkup(<WorkProgress progress={workProgress(undefined)} runs={[]} open={false} onOpen={()=>{}} onSelect={()=>{}} onAction={()=>{}} onEvidence={()=>{}} onCurrent={()=>{}}/>);assert.equal(empty,'');
});
test('event refresh stays scoped and ignores token streaming',()=>{
 const bound={...run,event_id:'e'};
 assert.equal(eventRefreshSequence(bound,[row(1,'verification',{}),row(2,'text_delta',{}),row(3,'verification',{},'other')]),1);
 assert.equal(eventRefreshSequence(run,[row(1,'verification',{})]),0);
});
test('text, Word, confirmation and old event files keep their distinct identities',()=>{
 const text={format:'text',title:'公告',run_id:run.id} as never;
 const p=workProgress({...run,stage:'announcement',status:'completed',documents:[text]});assert.equal(p.title,'公告正文已保存');assert.equal(p.action,'documents');
 const confirmation=workProgress({...run,stage:'confirmation',status:'completed',documents:[{format:'text'} as never]});assert.equal(confirmation.title,'正文确认已记录');assert.doesNotMatch(confirmation.detail,/文件生成/);
 const old=workProgress({...run,stage:'word',status:'completed',artifact_id:'old-file'});assert.equal(old.action,'review');assert.equal(old.actionLabel,'查看事项文稿');
 const unknown=workProgress({...run,stage:'announcement',status:'completed'});assert.doesNotMatch(unknown.title,/已保存|已生成/);
});
test('applied or cancelled knowledge proposals remain historical observations, not pending work',()=>{
 const rows=[row(1,'knowledge_proposal',{summary:'修订条目'}),row(2,'knowledge_applied',{})];
 const applied=workProgress({...run,stage:'knowledge',status:'completed'},rows);assert.equal(applied.title,'知识库变更已执行');assert.ok(applied.activities.every(a=>a.state==='done'));assert.equal(applied.action,undefined);
 const cancelled=workProgress({...run,stage:'knowledge',status:'completed'},rows.slice(0,1));assert.equal(cancelled.activities[0].state,'done');assert.equal(cancelled.action,undefined);
});
