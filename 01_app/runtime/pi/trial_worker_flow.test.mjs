// Full-repository integration: real Pi Agent, simulated provider and business bridge.
import test from 'node:test';
import assert from 'node:assert/strict';
import {AssistantMessageEventStream} from '@earendil-works/pi-ai';
import {execute} from './worker.mjs';
const model={id:'trial-fixture',provider:'fixture',api:'openai-completions',name:'Offline fixture',baseUrl:'http://127.0.0.1:1',reasoning:false,input:['text'],contextWindow:128000,maxTokens:1024,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const packet={model,system:'仅虚构接口测试',history:[],prompt:'模拟请求',apiKey:'fixture-key',tools:[],session_id:'trial-flow-fixture'};
const tool=name=>({name,description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}});
function stream(content,stopReason='stop') {
 const s=new AssistantMessageEventStream();
 const message={role:'assistant',content,api:model.api,provider:model.provider,model:model.id,
  usage:{input:10,output:10,cacheRead:0,cacheWrite:0,totalTokens:20,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason,timestamp:Date.now()};
 s.push({type:'start',partial:message});s.push({type:'done',reason:stopReason,message});return s;
}
const call=(name,id)=>stream([{type:'toolCall',id,name,arguments:{}}],'toolUse');

test('Word: mistaken unavailable prose is repaired through preflight then exactly one production call',async()=>{
 const events=[],calls=[];let round=0;
 await execute({...packet,stage:'auto',routeFirst:true,tools:[tool('route_request')]},e=>events.push(e),async(id,name)=>{
  calls.push(name);
  if(name==='route_request')return {data:{stage:'document'},next_context:{system:'preflight',system_sha256:'p',stage:'document_preflight',requires_result:true,tools:[tool('assess_document_readiness')]}};
  if(name==='assess_document_readiness')return {data:{status:'ready'},next_context:{system:'ready',system_sha256:'r',stage:'document',requires_result:true,tools:[tool('make_word'),tool('assess_document_readiness')]}};
  assert.equal(name,'make_word');return {data:{documents:[{document_id:'fixture-doc'}]},terminate:true,finalize:true};
 },(m,ctx)=>{
  round++;
  if(round===1)return call('route_request','route');
  if(round===2)return stream([{type:'text',text:'make_word 当前不可用，只提供正文。'}]);
  if(round===3){assert.match(JSON.stringify(ctx.messages.at(-1)),/assess_document_readiness/);return call('assess_document_readiness','check');}
  if(round===4){assert.ok(ctx.tools.some(t=>t.name==='make_word'));return call('make_word','write');}
  assert.equal(round,5);assert.deepEqual(ctx.tools,[]);return stream([{type:'text',text:'测试文件已登记，待审阅。'}]);
 });
 assert.deepEqual(calls,['route_request','assess_document_readiness','make_word']);
 assert.ok(events.some(e=>e.type==='phase_started'&&e.stage==='document'));
 assert.ok(events.some(e=>e.type==='finalization_completed'));
 assert.equal(events.at(-1).type,'done');
 assert.notEqual(events.at(-1).completion_complete,false);
});

for(const stage of ['chat','knowledge']) {
 test(`${stage}: empty stop after lookup repairs into an answer`,async()=>{
  const events=[];let round=0;
  await execute({...packet,stage,requires_result:false,tools:[tool('lookup')]},e=>events.push(e),async()=>({data:{text:'模拟资料'}}),(m,ctx)=>{
   round++;
   if(round===1)return call('lookup','lookup');
   if(round===2)return stream([]);
   assert.equal(round,3);assert.match(JSON.stringify(ctx.messages.at(-1)),/完整答复/);
   return stream([{type:'text',text:'依据模拟资料，以下为办理说明。'}]);
  });
  assert.equal(events.filter(e=>e.type==='completion_repair_started').length,1);
  assert.notEqual(events.at(-1).completion_complete,false);
 });
 test(`${stage}: persistent empty stops cannot emit a successful completion`,async()=>{
  const events=[];let calls=0;const cancel=new AbortController();
  await assert.rejects(execute({...packet,stage,requires_result:false},e=>events.push(e),()=>assert.fail('no business tool'),()=>{if(++calls===12)cancel.abort();return stream([]);},cancel.signal),/Cancelled/);
  assert.equal(calls,12);assert.ok(!events.some(e=>e.type==='done'));
 });
}
test('restored historical answer is not completion of a new empty turn',async()=>{
 const events=[];
 const history=[{role:'user',content:'旧问题',timestamp:1},{role:'assistant',content:[{type:'text',text:'旧答复'}],api:model.api,provider:model.provider,model:model.id,stopReason:'stop',timestamp:2}];
 const cancel=new AbortController();let rounds=0;
 await assert.rejects(execute({...packet,stage:'chat',history},e=>events.push(e),()=>assert.fail(),()=>{if(++rounds===12)cancel.abort();return stream([]);},cancel.signal),/Cancelled/);
 assert.ok(!events.some(e=>e.type==='done'));
});
test('valid read answer is not followed by a redundant model call',async()=>{
 let calls=0;const events=[];
 await execute({...packet,stage:'chat'},e=>events.push(e),()=>assert.fail(),()=>{calls++;return stream([{type:'text',text:'正常答复'}]);});
 assert.equal(calls,1);assert.equal(events.at(-1).type,'done');
});

test('consultation prose answer completes without forcing a registration tool',async()=>{
 const events=[];let rounds=0;
 await execute({...packet,stage:'chat',requires_result:false,tools:[tool('submit_consultation')]},e=>events.push(e),()=>assert.fail('no tool call expected'),(m,ctx)=>{
  rounds++;return stream([{type:'text',text:'咨询答复可先展示，依据仍可后续登记。'}]);
 });
 assert.equal(rounds,1);
 assert.ok(!events.some(e=>e.type==='completion_repair_started'));
 assert.equal(events.at(-1).type,'done');
});
