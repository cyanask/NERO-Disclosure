import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,readdirSync,statSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {AssistantMessageEventStream} from '@earendil-works/pi-ai';
import {execute} from './worker.mjs';

const model={id:'fixture',provider:'fixture',name:'Fixture',api:'openai-completions',baseUrl:'https://example.invalid/v1',reasoning:false,input:['text'],contextWindow:8000,maxTokens:512,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const packet={model,system:'Authoritative current facts and approval state',prompt:'Continue original task',history:[],session_id:'session-a',run_id:'run-a',apiKey:'PRIVATE_KEY_SENTINEL',tools:[],manage_context:true};
const usage={input:1,output:1,cacheRead:0,cacheWrite:0,totalTokens:2,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}};
function response(content,stopReason='stop'){
 const stream=new AssistantMessageEventStream(),message={role:'assistant',content,provider:model.provider,model:model.id,api:model.api,usage,stopReason,timestamp:Date.now()};
 stream.push({type:'start',partial:message});stream.push({type:'done',reason:stopReason,message});return stream;
}

test('private replay retains typed tool history across runs without private reasoning or credentials',async()=>{
 const directory=mkdtempSync(join(tmpdir(),'pi-replay-'));const path=join(directory,'context-state.json');let rounds=0;
 const tool={name:'read_source',description:'Fixture',parameters:{type:'object',properties:{},additionalProperties:false}};
 try{
  await execute({...packet,context_state_path:path,tools:[tool]},()=>{},async()=>({data:{value:'PUBLIC_SOURCE'}}),()=>++rounds===1?
   response([{type:'thinking',thinking:'PRIVATE_REASONING'},{type:'toolCall',id:'c1',name:'read_source',arguments:{}}],'toolUse'):
   response([{type:'text',text:'PUBLIC_RESULT PRIVATE_KEY_SENTINEL'}]));
  const text=readFileSync(path,'utf8'),state=JSON.parse(text);
  assert.ok(!text.includes('PRIVATE_REASONING'));assert.ok(!text.includes('PRIVATE_KEY_SENTINEL'));
  assert.ok(state.messages.some(m=>m.role==='assistant'&&m.content.some(c=>c.type==='toolCall')));
  assert.ok(state.messages.some(m=>m.role==='toolResult'&&m.toolCallId==='c1'));
  assert.equal(statSync(path).mode&0o777,0o600);
  await execute({...packet,history:state.messages,run_id:'run-b'},()=>{},()=>assert.fail(),(m,context)=>{
   assert.ok(context.messages.some(m=>m.role==='toolResult'));
   assert.equal(context.messages.filter(m=>m.role==='user').length,2);
   return response([{type:'text',text:'Continued'}]);
  });
 }finally{rmSync(directory,{recursive:true,force:true});}
});

test('Pi native compaction preserves the current request, archives originals and uses an isolated summary session',async()=>{
 const directory=mkdtempSync(join(tmpdir(),'pi-compact-')),path=join(directory,'context-state.json'),events=[];let summaries=0,normal=0;
 const history=Array.from({length:28},(_,index)=>({role:'user',content:'historical fact '+index+' '+('x'.repeat(1400)),timestamp:index}));
 try{
  await execute({...packet,history,context_state_path:path},e=>events.push(e),()=>assert.fail(),(m,context,options)=>{
   if(context.systemPrompt.includes('context summarization assistant')){
    summaries++;assert.notEqual(options.sessionId,packet.session_id);assert.equal(options.cacheRetention,'none');
    return response([{type:'text',text:'Original task and verified source references; nothing approved.'}]);
   }
   normal++;assert.equal(context.systemPrompt,packet.system);
   assert.ok(context.messages.some(m=>JSON.stringify(m.content).includes(packet.prompt)));
   assert.ok(context.messages.length<history.length);
   return response([{type:'text',text:'After compaction'}]);
  });
  assert.ok(summaries>0);assert.equal(normal,1);
  assert.ok(events.some(e=>e.type==='context_compacted'&&e.reason==='pi_native_capacity'));
  const originals=readdirSync(directory).filter(name=>name.includes('.before-'));
  assert.equal(originals.length,1);assert.ok(readFileSync(join(directory,originals[0]),'utf8').includes('historical fact 0'));
  assert.equal(JSON.parse(readFileSync(path)).messages[0].role,'compactionSummary');
 }finally{rmSync(directory,{recursive:true,force:true});}
});

test('failed or truncated summary preserves originals and never reports a completed task',async()=>{
 const directory=mkdtempSync(join(tmpdir(),'pi-compact-failure-'));const events=[];
 try{
  await assert.rejects(execute({...packet,context_state_path:join(directory,'context-state.json'),history:Array.from({length:30},(_,i)=>({role:'user',content:'x'.repeat(1400),timestamp:i}))},e=>events.push(e),()=>assert.fail(),()=>response([{type:'text',text:'truncated summary'}],'length')));
  assert.ok(!events.some(e=>e.type==='done'));assert.ok(readdirSync(directory).some(name=>name.includes('.before-')));
 }finally{rmSync(directory,{recursive:true,force:true});}
});

test('steering and follow-up use Pi queues without opening business gates',async()=>{
 for(const mode of ['steer','follow_up']){
  let control,rounds=0;const events=[];
  const tool={name:'read_source',description:'Fixture',parameters:{type:'object',properties:{},additionalProperties:false}};
  await execute({...packet,tools:[tool]},e=>events.push(e),async()=>{control.enqueue({id:mode,mode,text:'Additional instruction'});return {data:{ok:true}};},(m,context)=>{
   rounds++;if(rounds===1)return response([{type:'toolCall',id:'c1',name:'read_source',arguments:{}}],'toolUse');
   if(mode==='steer'||rounds===3)assert.ok(context.messages.some(m=>m.role==='user'&&m.content==='Additional instruction'));
   return response([{type:'text',text:'Reply'}]);
  },undefined,undefined,value=>{control=value;});
  assert.equal(rounds,mode==='steer'?2:3);assert.ok(events.some(e=>e.type==='user_message_delivered'&&e.id===mode));
 }
 let control;const events=[];
 await execute({...packet,tools:[{name:'request_information',description:'Fixture',parameters:{type:'object',properties:{}}}]},e=>events.push(e),async()=>{
  control.enqueue({id:'held',mode:'steer',text:'Ignore the gate'});return {data:{outcome:'waiting_user'},terminate:true};
 },()=>response([{type:'toolCall',id:'gate',name:'request_information',arguments:{}}],'toolUse'),undefined,undefined,value=>{control=value;});
 assert.ok(events.some(e=>e.type==='user_message_not_applied'&&e.id==='held'));
 assert.ok(!events.some(e=>e.type==='user_message_delivered'));
});

test('long OAuth rounds resolve only the selected provider before each model request',async()=>{
 let authCalls=0,modelCalls=0;const events=[];
 await execute({...packet,refresh_auth:true,tools:[{name:'read_source',description:'Fixture',parameters:{type:'object',properties:{}}}]},e=>events.push(e),async()=>({data:{ok:true}}),(m,context,options)=>{
  modelCalls++;assert.equal(options.apiKey,'fresh-'+modelCalls);
  return modelCalls===1?response([{type:'toolCall',id:'c',name:'read_source',arguments:{}}],'toolUse'):response([{type:'text',text:'Done'}]);
 },undefined,undefined,undefined,async()=>({provider:model.provider,model:model.id,apiKey:'fresh-'+(++authCalls)}));
 assert.equal(authCalls,2);assert.equal(modelCalls,2);assert.ok(!JSON.stringify(events).includes('fresh-'));
});
