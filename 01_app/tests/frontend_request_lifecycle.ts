import assert from 'node:assert/strict';
import {test} from 'node:test';
import {withDeadline} from '../frontend/src/requestLifetime';
import {recoverService,RestartRejected} from '../frontend/src/serviceRecovery';
import {ViewRequests,readEvents,readDeliverySources} from '../frontend/src/workspaceRequests';

const service={instance_id:'new',pending:false,supported:true,can_restart:true,reason:'',error:''};
test('whole-operation deadline bounds a hung response body and session restore',async()=>{
 let aborted=false;
 await assert.rejects(withDeadline(signal=>{signal.addEventListener('abort',()=>aborted=true);return new Promise(()=>{});},10),/超时/);
 assert.equal(aborted,true);
 await assert.rejects(recoverService('old',new AbortController().signal,{timeoutMs:35,attemptMs:5,intervalMs:1,io:{state:async()=>service,session:()=>new Promise(()=>{})}}),/暂未确认服务恢复/);
});
test('navigation cancellation aborts recovery before a late session can commit',async()=>{
 const controller=new AbortController();let release:(value:{csrf_token:string})=>void=()=>{};
 const pending=recoverService('old',controller.signal,{io:{state:async()=>service,session:()=>new Promise(resolve=>{release=resolve;controller.abort(new Error('left page'));})}});
 await assert.rejects(pending,/left page/);release({csrf_token:'late'});
});
test('recovery observes a new instance and gets fresh credentials without a restart write',async()=>{
 let reads=0,sessions=0;
 const result=await recoverService('old',new AbortController().signal,{intervalMs:1,io:{state:async()=>({...service,instance_id:++reads===1?'old':'new'}),session:async()=>{sessions++;return {csrf_token:'fresh'};}}});
 assert.equal(reads,2);assert.equal(sessions,1);assert.equal(result.csrf,'fresh');
 await assert.rejects(recoverService('old',new AbortController().signal,{io:{state:async()=>({...service,error:'launcher failed'}),session:async()=>({csrf_token:'unused'})}}),RestartRejected);
});
test('every view transition invalidates pending data, even when the transport ignores abort',async()=>{
 const scope=new ViewRequests(),old=scope.capture();let apply=false;
 const delayed=Promise.resolve().then(()=>{if(old.current())apply=true;});scope.invalidate();await delayed;
 assert.equal(apply,false);assert.equal(old.signal.aborted,true);assert.equal(scope.capture().current(),true);
 scope.invalidate();assert.equal(old.current(),false);
});
test('event refresh never depends on documents and delivery sources fail independently',async()=>{
 const original=globalThis.fetch;const calls:string[]=[];
 globalThis.fetch=async input=>{const url=String(input);calls.push(url);return url.startsWith('/api/events?')?new Response(JSON.stringify([{id:'event'}])):new Response(JSON.stringify({detail:'files unavailable'}),{status:503});};
 try{
  assert.deepEqual(await readEvents('chinext','300001'),[{id:'event'}]);assert.equal(calls.length,1);
  const result=await readDeliverySources('chinext','300001');
  assert.equal(result.events.status,'fulfilled');assert.equal(result.documents.status,'rejected');
 }finally{globalThis.fetch=original;}
});
