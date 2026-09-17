import assert from 'node:assert/strict';
import {test} from 'node:test';
import {watchConfirmation,observeContinuation,continuationFailure,restoreContinuation} from '../frontend/src/confirmationContinuation';
import type {ResumePending} from '../frontend/src/confirmationContinuation';
import type {DisclosureEvent} from '../frontend/src/types';
import type {PiRun,Receipt} from '../frontend/src/chat';

const event={id:'e',approval_records:[{id:'approval',state:'current'}]} as DisclosureEvent;
const watch:ResumePending={sid:'s',eventId:'e',parent:'parent',approvalId:'approval',requestedAt:10};
const parent={id:'parent',session_id:'s',event_id:'e',status:'completed',created:1,resume_after_settle:'approval'} as PiRun;
const child={id:'child',session_id:'s',event_id:'e',status:'running',created:12} as PiRun;
const receipt=(kind:string,body:object,run_id='parent',at=11)=>({kind,body,run_id,at,seq:1} as Receipt);

test('accepted confirmation watches the exact returned run, not arbitrary latest work',()=>{
 const pending=watchConfirmation({status:'accepted',run_id:'child'},event,'s',10)!;
 assert.equal(pending.runId,'child');
 assert.equal(observeContinuation(pending,[parent],[]).action,'waiting');
 assert.equal(observeContinuation(pending,[{...child,session_id:'other'}],[]).action,'waiting');
 assert.equal(observeContinuation(pending,[child],[]).action,'reload');
});
test('queued continuation remains waiting while backend still owns a pending handoff',()=>{
 const pending=watchConfirmation({status:'queued',run_id:'parent'},event,'s',10)!;
 assert.equal(pending.parent,'parent');
 // A terminal parent alone does not establish failure: a delayed continuation
 // can still be pending after three or more polling responses.
 for(let poll=0;poll<8;poll++)assert.equal(observeContinuation(pending,[parent],[]).action,'waiting');
 assert.equal(observeContinuation(pending,[],[]).action,'waiting');
});
test('backend continuation ID safely handles the child appearing on a later read',()=>{
 const linked={...parent,resume_after_settle:null,resume_confirmation_id:'approval',continuation_run_id:'child'};
 assert.equal(observeContinuation(watch,[linked],[]).action,'waiting');
 assert.equal(observeContinuation(watch,[child,linked],[]).action,'reload');
 // Reload also displays a failed child truthfully; observing a run is not completion.
 assert.equal(observeContinuation(watch,[{...child,status:'failed'},linked],[]).action,'reload');
});
test('human_resume receipts must belong to this confirmation and session',()=>{
 assert.equal(observeContinuation(watch,[child,parent],[receipt('human_resume',{approval_id:'other'},'child')]).action,'waiting');
 assert.equal(observeContinuation(watch,[child,parent],[receipt('human_resume',{approval_id:'approval'},'elsewhere')]).action,'waiting');
 assert.equal(observeContinuation(watch,[child,parent],[receipt('human_resume',{approval_id:'approval'},'child')]).action,'reload');
});
test('late backend failure exposes its reason and releases the wait',()=>{
 const result=observeContinuation(watch,[parent],[receipt('continuation_failed',{reason:'原模型配置已变化'})]);
 assert.deepEqual(result,{action:'failed',reason:'原模型配置已变化'});
 assert.equal(observeContinuation(watch,[parent],[receipt('continuation_failed',{reason:'旧失败'},'parent',9)]).action,'waiting');
 assert.equal(observeContinuation(watch,[{...parent,resume_after_settle:null}],[]).action,'failed');
});
test('a real pause or cancellation ends observation without claiming completion',()=>{
 assert.equal(observeContinuation(watch,[{...parent,resume_cancelled_for:'approval',resume_after_settle:null}],[]).action,'paused');
 assert.equal(observeContinuation(watch,[parent],[receipt('continuation_paused',{reason:'使用者暂停自动接续'})]).action,'paused');
 assert.equal(observeContinuation(watch,[{...parent,status:'cancelled',reason:'使用者停止'}],[]).action,'failed');
});
test('unconfigured or blocked continuation is not silently hidden after saving confirmation',()=>{
 assert.equal(continuationFailure({status:'not_configured',reason:'原会话缺失'}),'原会话缺失');
 assert.equal(continuationFailure({status:'blocked',reason:'模型已变化'}),'模型已变化');
 assert.equal(watchConfirmation({status:'not_required'},event,'s',10),undefined);
 assert.equal(watchConfirmation({status:'paused'},event,'s',10),undefined);
});

test('reopening a session recovers a still-queued continuation from current approval state',()=>{
 const recovered=restoreContinuation(event,'s',[{...parent,updated:11}]);
 assert.equal(recovered?.parent,'parent');assert.equal(recovered?.approvalId,'approval');
 assert.equal(restoreContinuation({...event,approval_records:[{id:'approval',state:'invalidated'} as never]},'s',[parent]),undefined);
 assert.equal(restoreContinuation(event,'other',[parent]),undefined);
 assert.equal(restoreContinuation(event,'s',[{...parent,resume_after_settle:null}]),undefined);
});
