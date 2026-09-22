import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { AssistantMessageEventStream, registerSessionResourceCleanup } from '@earendil-works/pi-ai';
import { execute, executionErrorMessage } from './worker.mjs';
import { brokerOptions, BROKER_PROVIDER, BROKER_BASE_URL } from './broker_compat.mjs';

const model={id:'offline-fixture',provider:'fixture',api:'openai-completions',name:'Offline fixture',baseUrl:'http://127.0.0.1:1',reasoning:false,input:['text'],contextWindow:128000,maxTokens:1024,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const packet={model,system:'仅离线接口测试',history:[],prompt:'测试公开事件',apiKey:'fixture-key',tools:[],session_id:'test'};

test('public errors never expose arbitrary provider details',()=>{assert.doesNotMatch(executionErrorMessage(new Error('PRIVATE_DETAIL')),/PRIVATE_DETAIL/);});

for (const attempts of [4, 12]) {
 test(`consultation evidence repair can reach submission ${attempts} without a business-candidate quota`,async()=>{
  const events=[],submitted=[];let rounds=0;
  await execute({...packet,stage:'chat',requires_result:true,tools:[fixtureTool('submit_consultation')]},e=>events.push(e),async(id,name)=>{
   submitted.push(name);
   return submitted.length<attempts
    ? {data:{status:'repair_evidence',issues:[{reason:'离线样本：本次仍须修正依据'}]}}
    : {data:{status:'completed'},terminate:true};
  },(m,ctx,opts)=>{
   rounds++;
   // Stop the fake provider after the planned sequence so a regression cannot
   // spin forever when an intercepted tool call never reaches the bridge.
   if(rounds>attempts)return stream([{type:'text',text:'离线样本仍未获得登记结果'}])(m,ctx,opts);
   return stream([{type:'toolCall',id:'consult-'+rounds,name:'submit_consultation',arguments:{}}],'toolUse')(m,ctx,opts);
  });
  assert.equal(submitted.length,attempts);
  assert.equal(events.at(-1).type,'done');
  assert.notEqual(events.at(-1).completion_complete,false);
 });
}

test('rejected drafts can keep repairing until the user cancels',async()=>{
 const events=[];let submitted=0;const cancel=new AbortController();
 await assert.rejects(execute({...packet,stage:'chat',requires_result:true,tools:[fixtureTool('submit_consultation')]},e=>events.push(e),async()=>{
  if(++submitted===15)cancel.abort();return {data:{status:'repair_evidence'}};
 },(m,c,o)=>stream([{type:'toolCall',id:'repair-'+submitted,name:'submit_consultation',arguments:{}}],'toolUse')(m,c,o),cancel.signal),/Cancelled/);
 assert.equal(submitted,15);assert.ok(!events.some(e=>e.type==='done'));
});

test('consultation prose answer completes without a forced submission',async()=>{
 const events=[];let rounds=0;
 await execute({...packet,stage:'chat',requires_result:false,tools:[fixtureTool('submit_consultation')]},e=>events.push(e),()=>assert.fail('consultation must not be forced into a tool call'),(m,ctx,opts)=>{
  rounds++;return stream([{type:'text',text:'咨询答复可直接展示，依据登记由主控自行判断。'}])(m,ctx,opts);
 });
 assert.equal(rounds,1);
 assert.ok(!events.some(e=>e.type==='completion_repair_started'));
 assert.equal(events.at(-1).type,'done');
});

test('native preflight reaches one waiting-user boundary and closes tools',async()=>{
 const events=[],calls=[];let round=0;
 await execute({...packet,stage:'chat',tools:[fixtureTool('assess_document_readiness')]},e=>events.push(e),async(id,name)=>{
  calls.push(name);return {data:{status:'waiting_user'},terminate:true,finalize:true};
 },(m,ctx,opts)=>{
  round++;if(round===1)return stream([{type:'toolCall',id:'check',name:'assess_document_readiness',arguments:{}}],'toolUse')(m,ctx,opts);
  assert.equal(round,2);assert.deepEqual(ctx.tools,[]);return stream([{type:'text',text:'等待你处理已列出的缺口。'}])(m,ctx,opts);
 });
 assert.deepEqual(calls,['assess_document_readiness']);assert.ok(!events.some(e=>e.type==='completion_repair_started'));
 assert.ok(events.some(e=>e.type==='finalization_completed'));assert.equal(events.at(-1).type,'done');
});
function stream(content,stopReason='stop'){
 return ()=>{const s=new AssistantMessageEventStream();const message={role:'assistant',content,api:model.api,provider:model.provider,model:model.id,usage:{input:10,output:10,cacheRead:0,cacheWrite:0,totalTokens:20,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason,timestamp:Date.now()};
  s.push({type:'start',partial:message});s.push({type:'text_delta',contentIndex:0,delta:'离线测试结果',partial:message});
  if(stopReason==='error')s.push({type:'error',reason:'error',error:message});else s.push({type:'done',reason:stopReason,message});return s;};
}
test('real Pi Agent emits public text and filters reasoning',async()=>{
 const events=[];await execute(packet,e=>events.push(e),()=>assert.fail(),stream([{type:'text',text:'离线测试结果'},{type:'thinking',thinking:'PRIVATE_REASONING_SENTINEL'}]));
 assert.equal(events[0].type,'started');assert.ok(events.some(e=>e.type==='text_delta'));assert.equal(events.at(-1).type,'done');
 assert.ok(!JSON.stringify(events).includes('PRIVATE_REASONING_SENTINEL'));
});
test('real Pi validates and executes bridge tool then terminates without another model call',async()=>{
 const events=[],calls=[];let rounds=0;
 const tool={name:'read_event',description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}};
 await execute({...packet,tools:[tool]},e=>events.push(e),async(id,name,args)=>{calls.push({id,name,args});return {data:{verified:true},terminate:true};},(...args)=>{rounds++;return stream([{type:'toolCall',id:'call1',name:'read_event',arguments:{}}],'toolUse')(...args);});
 assert.equal(rounds,1);assert.equal(calls[0].name,'read_event');assert.equal(events.at(-1).calls,1);
});
test('provider failure cannot produce successful done receipt',async()=>{
 const events=[];await assert.rejects(execute(packet,e=>events.push(e),()=>assert.fail(),stream([],'error')));
 assert.ok(!events.some(e=>e.type==='done'));
});
test('selected max effort reaches the real Pi stream options without downgrade',async()=>{
 const events=[];let observed;
 await execute({...packet,reasoning_effort:'max',model:{...model,reasoning:true,thinkingLevelMap:{low:'low',medium:'medium',high:'high',xhigh:'xhigh',max:'max'}}},e=>events.push(e),()=>assert.fail(),(m,context,options)=>{observed=options;return stream([{type:'text',text:'ok'}])(m,context,options);});
 assert.equal(observed.reasoning,'max');assert.equal(observed.maxRetries,undefined);assert.equal(events[0].reasoning_effort,'max');
});
test('tool errors propagate into Pi follow-up without successful tool receipt',async()=>{
 let rounds=0;const events=[];
 const tool={name:'read_event',description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}};
 await execute({...packet,tools:[tool]},e=>events.push(e),async()=>{throw new Error('scope blocked');},(m,ctx,opts)=>{
  rounds++;if(rounds===2)assert.ok(ctx.messages.some(x=>x.role==='toolResult'&&x.isError));
  return (rounds===1?stream([{type:'toolCall',id:'call1',name:'read_event',arguments:{}}],'toolUse'):stream([{type:'text',text:'工具未执行'}]))(m,ctx,opts);
 });assert.equal(rounds,2);assert.equal(events.at(-1).type,'done');
});

test('Banker broker payload compatibility reaches the existing Pi model stream',async()=>{
 let observed;
 const selected={...model,provider:BROKER_PROVIDER,api:'openai-responses',baseUrl:BROKER_BASE_URL,id:'google-antigravity/gemini-3.8-flash'};
 await execute({...packet,model:selected,reasoning_effort:'high'},()=>{},()=>assert.fail(),(m,ctx,opts)=>{
  observed=opts;return stream([{type:'text',text:'offline broker fixture'}])(m,ctx,opts);
 });
 const payload={model:selected.id,max_output_tokens:8192,service_tier:'priority',reasoning:{effort:'high'},tools:[{type:'function',name:'read_event'}]};
 const wire=await observed.onPayload(payload,selected);
 assert.equal(wire.max_output_tokens,undefined);assert.equal(wire.service_tier,undefined);
 assert.deepEqual(wire.reasoning,payload.reasoning);assert.deepEqual(wire.tools,payload.tools);
 assert.equal(wire.model,selected.id);assert.equal(payload.max_output_tokens,8192);
 const native={maxTokens:8192};assert.equal(brokerOptions(model,native),native);
 assert.throws(()=>brokerOptions({...selected,baseUrl:'https://example.invalid'},native));
});


test('a source review can finish after twelve sequential tool rounds',async()=>{
 let rounds=0; const events=[];
 const tool={name:'read_source',description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}};
 await execute({...packet,tools:[tool]},e=>events.push(e),async()=>({data:{text:'source'}}),(m,ctx,opts)=>{
   rounds++;
   return (rounds<=13?stream([{type:'toolCall',id:'source'+rounds,name:'read_source',arguments:{}}],'toolUse'):stream([{type:'text',text:'review complete'}]))(m,ctx,opts);
 });
 assert.equal(rounds,14);assert.equal(events.at(-1).type,'done');assert.equal(events.at(-1).calls,13);
});

test('research remains available beyond prior tool and model-turn caps',async()=>{
 let calls=0,rounds=0;const events=[];
 const tool={name:'read_source',description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}};
 await execute({...packet,tools:[tool]},e=>events.push(e),async()=>{calls++;return {data:{text:'source'}};},(m,ctx,opts)=>{
  rounds++;return (rounds<=70?stream([{type:'toolCall',id:'source'+rounds,name:'read_source',arguments:{}}],'toolUse'):stream([{type:'text',text:'review complete'}]))(m,ctx,opts);
 });
 assert.equal(calls,70);assert.equal(events.at(-1).type,'done');
 assert.ok(!JSON.stringify(events).includes('资料读取额度已用完'));
});

test('research does not consume the reserved candidate submission',async()=>{
 let rounds=0; const events=[],calls=[];
 const tool=name=>({name,description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}});
 await execute({...packet,tools:[tool('read_source'),tool('submit_candidate')]},e=>events.push(e),async(id,name)=>{
  calls.push(name);return {data:{ok:true},terminate:name==='submit_candidate'};
 },(m,ctx,opts)=>{rounds++;const name=rounds<=40?'read_source':'submit_candidate';return stream([{type:'toolCall',id:'c'+rounds,name,arguments:{}}],'toolUse')(m,ctx,opts)});
 assert.equal(calls.filter(n=>n==='read_source').length,40);
 assert.equal(calls.at(-1),'submit_candidate');assert.equal(events.at(-1).type,'done');
});

test('registered result gets one closing answer from the same Pi with tools disabled',async()=>{
 let rounds=0;const events=[],calls=[];
 const tool={name:'submit_candidate',description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}};
 await execute({...packet,tools:[tool]},e=>events.push(e),async(id,name)=>{calls.push(name);return {data:{outcome:'waiting_approval',result_snapshot:{revision:9,stage:'assessment',result:{summary:'需披露，时点待核实'}}},terminate:true,finalize:true};},(m,ctx,opts)=>{
  rounds++;assert.equal(m.id,model.id);
  if(rounds===2){assert.equal(ctx.tools.length,0);assert.ok(JSON.stringify(ctx.messages).includes('需披露，时点待核实'));}
  return (rounds===1?stream([{type:'text',text:'正在提交'},{type:'toolCall',id:'submit',name:'submit_candidate',arguments:{}}],'toolUse'):stream([{type:'text',text:'需要披露，具体时点仍待核实。请审阅本轮判断。'}]))(m,ctx,opts);
 });
 assert.equal(rounds,2);assert.deepEqual(calls,['submit_candidate']);
 assert.equal(events.filter(e=>e.type==='started').length,1);
 assert.ok(events.some(e=>e.type==='assistant'&&e.phase==='final'&&e.text.includes('具体时点')));
 assert.ok(events.some(e=>e.type==='finalization_completed'));
});

test('closing failure preserves business completion and does not execute an extra tool',async()=>{
 let rounds=0,calls=0;const events=[];
 const tool={name:'submit_candidate',description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}};
 await execute({...packet,tools:[tool]},e=>events.push(e),async()=>{calls++;return {data:{outcome:'waiting_approval'},terminate:true,finalize:true};},(m,ctx,opts)=>{
  rounds++;
  return (rounds===1?stream([{type:'toolCall',id:'submit',name:'submit_candidate',arguments:{}}],'toolUse'):stream([{type:'toolCall',id:'illegal',name:'submit_candidate',arguments:{}}],'toolUse'))(m,ctx,opts);
 });
 assert.equal(calls,1);assert.equal(rounds,2);assert.ok(events.some(e=>e.type==='finalization_failed'));assert.equal(events.at(-1).type,'done');
});

test('same Pi applies the explicit workflow context and preserves public progress',async()=>{
 const events=[];let rounds=0;const calls=[];
 const route={name:'prepare_disclosure_workflow',description:'domain',parameters:{type:'object',properties:{},additionalProperties:false}};
 const search={name:'knowledge_search',description:'read-only',parameters:{type:'object',properties:{},additionalProperties:false}};
 await execute({...packet,tools:[route]},e=>events.push(e),async(id,name)=>{
  calls.push(name);return name==='prepare_disclosure_workflow'?{data:{domain:'knowledge'},next_context:{system:'knowledge only',system_sha256:'checked',tools:[search]}}:{data:{items:[]}};
 },(m,ctx,opts)=>{
  rounds++;
  if(rounds===2){assert.deepEqual(ctx.tools.map(t=>t.name),['knowledge_search']);assert.equal(ctx.systemPrompt,'knowledge only');}
  const content=rounds===1?[{type:'text',text:'WORKFLOW_PROGRESS'},{type:'toolCall',id:'r',name:'prepare_disclosure_workflow',arguments:{}}]:rounds===2?[{type:'toolCall',id:'s',name:'knowledge_search',arguments:{}}]:[{type:'text',text:'知识查询已完成'}];
  return stream(content,rounds<3?'toolUse':'stop')(m,ctx,opts);
 });
 assert.deepEqual(calls,['prepare_disclosure_workflow','knowledge_search']);assert.ok(events.some(e=>e.type==='assistant'&&e.phase==='progress'&&e.text==='WORKFLOW_PROGRESS'));
 assert.ok(events.some(e=>e.type==='phase_started'));assert.equal(events.at(-1).type,'done');
});

const fixtureTool=name=>({name,description:'fixture',parameters:{type:'object',properties:{},additionalProperties:false}});

test('a lifecycle text answer does not fabricate a registration or force another prompt',async()=>{
 let rounds=0;const events=[];
 await execute({...packet,stage:'lifecycle',requires_result:true,tools:[fixtureTool('lifecycle_submit')]},e=>events.push(e),()=>assert.fail('no registration requested'),(m,c,o)=>{
  rounds++;return stream([{type:'text',text:'核验尚未登记'}])(m,c,o);
 });
 assert.equal(rounds,1);assert.equal(events.at(-1).calls,0);assert.ok(!events.some(e=>e.type==='completion_repair_started'));
});

test('session resources are cleaned on both successful and failed provider calls',async()=>{
 for (const stopReason of ['stop','error']) {
  const cleaned=[];
  const unregister=registerSessionResourceCleanup(id=>cleaned.push(id));
  try {
   const run=execute({...packet,session_id:'owned-session'},()=>{},()=>assert.fail(),stream([{type:'text',text:'retained'}],stopReason));
   if(stopReason==='error')await assert.rejects(run);else await run;
   assert.deepEqual(cleaned,['owned-session']);
  } finally {unregister();}
 }
});

test('routing, business and final answer all keep selected effort and output budget',async()=>{
 const events=[],options=[];let rounds=0;
 const route=fixtureTool('prepare_disclosure_workflow'),submit=fixtureTool('submit_candidate');
 await execute({...packet,requires_result:false,reasoning_effort:'max',maxTokens:12000,routing_reasoning_effort:'low',routing_max_tokens:900,tools:[route]},e=>events.push(e),async(id,name)=>name==='prepare_disclosure_workflow'?{
  data:{domain:'disclosure'},next_context:{system:'assessment',system_sha256:'assessment-hash',stage:'assessment',requires_result:true,tools:[submit]},
 }:{data:{saved:true},terminate:true,finalize:true},(m,ctx,opts)=>{
  options.push(opts);rounds++;
  return stream(rounds<3?[{type:'toolCall',id:'c'+rounds,name:rounds===1?'prepare_disclosure_workflow':'submit_candidate',arguments:{}}]:[{type:'text',text:'已登记，待人工确认'}],rounds<3?'toolUse':'stop')(m,ctx,opts);
 });
 assert.deepEqual(options.map(o=>[o.reasoning,o.maxTokens]),[['max',12000],['max',12000],['max',12000]]);
 assert.ok(events.filter(e=>['started','phase_started'].includes(e.type)).every(e=>e.reasoning_effort==='max'));
 const starts=events.filter(e=>e.type==='model_call_started'),ends=events.filter(e=>e.type==='model_call_finished');
 assert.deepEqual(starts.map(e=>e.phase),['working','working','final']);
 assert.equal(starts[1].stage,'assessment');assert.equal(ends.length,3);
 assert.ok(ends.every(e=>e.elapsed_ms>=0&&e.usage.totalTokens===20&&!('cost' in e.usage)));
});

test('the native tool loop can revise a rejected submission beyond the former caps',async()=>{
 const events=[];let rounds=0,submissions=0;
 await execute({...packet,stage:'assessment',tools:[fixtureTool('submit_candidate')]},e=>events.push(e),async()=>{
  return ++submissions<13?{data:{status:'revise'}}:{data:{saved:true},terminate:true};
 },(m,c,o)=>{rounds++;return stream([{type:'toolCall',id:'save-'+rounds,name:'submit_candidate',arguments:{}}],'toolUse')(m,c,o);});
 assert.equal(rounds,13);assert.equal(submissions,13);assert.ok(!events.some(e=>e.type==='completion_repair_started'));assert.equal(events.at(-1).type,'done');
});

test('native tool submissions advance successive workflow contexts before one closing reply',async()=>{
 const events=[],stages=['assessment','draft','review'];let rounds=0,submitted=0;const submit=fixtureTool('submit_candidate');
 await execute({...packet,stage:stages[0],tools:[submit]},e=>events.push(e),async()=>{
  submitted++;return submitted<3?{data:{result_snapshot:{stage:stages[submitted-1],result:{summary:'saved-'+submitted}}},
   next_context:{system:stages[submitted],system_sha256:'hash-'+submitted,stage:stages[submitted],tools:[submit]}}
   :{data:{saved:true},terminate:true,finalize:true};
 },(m,ctx,opts)=>{
  rounds++;if(rounds===2){assert.equal(ctx.systemPrompt,'draft');assert.ok(JSON.stringify(ctx.messages).includes('saved-1'));}
  if(rounds===3)assert.equal(ctx.systemPrompt,'review');if(rounds===4)assert.equal(ctx.tools.length,0);
  return stream(rounds<4?[{type:'toolCall',id:'s'+rounds,name:'submit_candidate',arguments:{}}]:[{type:'text',text:'已完成，待确认'}],rounds<4?'toolUse':'stop')(m,ctx,opts);
 });
 assert.equal(rounds,4);assert.equal(submitted,3);assert.equal(events.filter(e=>e.type==='finalization_started').length,1);
 assert.ok(!events.some(e=>e.type==='completion_repair_started'));assert.equal(events.at(-1).type,'done');
});

test('request information and other authoritative gates stop without correction or further tools',async()=>{
 for(const name of ['request_information','approval_gate']) {
  const events=[],calls=[];let rounds=0;
  await execute({...packet,stage:'assessment',requires_result:true,tools:[fixtureTool(name),fixtureTool('submit_candidate')]},e=>events.push(e),async(id,tool)=>{calls.push(tool);return {data:{status:'waiting'},terminate:true};},(m,ctx,opts)=>{
   rounds++;return stream([{type:'toolCall',id:'g',name,arguments:{}},{type:'toolCall',id:'s',name:'submit_candidate',arguments:{}}],'toolUse')(m,ctx,opts);
  });
  assert.equal(rounds,1);assert.deepEqual(calls,[name,'submit_candidate']);
  assert.ok(!events.some(e=>e.type==='completion_repair_started'));assert.equal(events.at(-1).type,'done');
 }
});

test('provider stream rejection closes its timing event and releases session resources',async()=>{
 const events=[],cleaned=[];
 const unregister=registerSessionResourceCleanup(id=>cleaned.push(id));
 try {
  await assert.rejects(execute(packet,e=>events.push(e),()=>assert.fail(),async()=>{throw new Error('fixture stream rejected');}));
  assert.deepEqual(cleaned,[packet.session_id]);
  assert.equal(events.filter(e=>e.type==='model_call_started').length,1);
  assert.equal(events.filter(e=>e.type==='model_call_finished').length,1);
  assert.equal(events.find(e=>e.type==='model_call_finished').stopReason,'error');
 } finally {unregister();}
});

test('native Pi starts independent tools in parallel',async()=>{
 let release;const together=new Promise(r=>{release=r;});const calls=[];let rounds=0;
 await execute({...packet,tools:[fixtureTool('read_a'),fixtureTool('read_b')]},()=>{},async(id,name)=>{
  calls.push(name);if(calls.length===2)release();
  await Promise.race([together,new Promise((_,reject)=>{const timer=setTimeout(()=>reject(new Error('tools ran serially')),1000);timer.unref();})]);
  return {data:{source:name}};
 },(m,c,o)=>stream(++rounds===1?[{type:'toolCall',id:'a',name:'read_a',arguments:{}},{type:'toolCall',id:'b',name:'read_b',arguments:{}}]:[{type:'text',text:'done'}],rounds===1?'toolUse':'stop')(m,c,o));
 assert.deepEqual(calls,['read_a','read_b']);
});

test('four business stages can each submit and only the final stage closes',async()=>{
 const events=[],stages=['assessment_a','assessment_b','timing','draft'];let submitted=0,rounds=0;
 const submit=fixtureTool('submit_candidate');
 await execute({...packet,stage:stages[0],requires_result:true,tools:[submit]},e=>events.push(e),async()=>{
  submitted++;
  return submitted<4?{data:{saved:true},terminate:true,finalize:true,next_context:{system:stages[submitted],system_sha256:'hash-'+submitted,stage:stages[submitted],requires_result:true,tools:[submit]}}
   :{data:{saved:true},terminate:true,finalize:true};
 },(m,ctx,opts)=>{
  rounds++;return stream(rounds<5?[{type:'toolCall',id:'s'+rounds,name:'submit_candidate',arguments:{}}]:[{type:'text',text:'四个节点均已登记，待人工确认'}],rounds<5?'toolUse':'stop')(m,ctx,opts);
 });
 assert.equal(submitted,4);assert.equal(rounds,5);
 assert.equal(events.filter(e=>e.type==='finalization_started').length,1);assert.equal(events.at(-1).type,'done');
});

test('candidate repair and context transitions continue past 3, 4 and 10',async()=>{
 const submit=fixtureTool('submit_candidate');let calls=0;
 await execute({...packet,stage:'assessment',requires_result:true,tools:[submit]},()=>{},async()=>{
  return ++calls<15?{data:{saved:false},next_context:{system:'assessment',stage:'assessment',requires_result:true,tools:[submit]}}:{data:{saved:true},terminate:true};
 },(m,c,o)=>stream([{type:'toolCall',id:'s'+calls,name:'submit_candidate',arguments:{}}],'toolUse')(m,c,o));
 assert.equal(calls,15);
});

test('the worker clears a long-lived session timer before exiting after done',async()=>{
 const childPacket={...packet,session_id:'exit-test'};
 const code=`
  import {execute} from './worker.mjs';
  import {AssistantMessageEventStream,registerSessionResourceCleanup} from '@earendil-works/pi-ai';
  const timer=setTimeout(()=>{},300000);
  registerSessionResourceCleanup(id=>{if(id==='exit-test')clearTimeout(timer);});
  const packet=${JSON.stringify(childPacket)};
  await execute(packet,event=>process.stdout.write(JSON.stringify(event)+'\\n'),()=>{},()=>{
   const stream=new AssistantMessageEventStream();
   const message={role:'assistant',content:[{type:'text',text:'OUTPUT_MUST_FLUSH'}],api:packet.model.api,provider:packet.model.provider,model:packet.model.id,stopReason:'stop',timestamp:Date.now()};
   stream.push({type:'start',partial:message});stream.push({type:'done',reason:'stop',message});return stream;
  });`;
 const {stdout}=await promisify(execFile)(process.execPath,['--input-type=module','-e',code],{cwd:fileURLToPath(new URL('.',import.meta.url)),timeout:3000});
 const events=stdout.trim().split('\n').map(line=>JSON.parse(line));
 assert.ok(events.some(e=>e.type==='assistant'&&e.text==='OUTPUT_MUST_FLUSH'));
 assert.equal(events.at(-2).type,'session_cleanup');assert.equal(events.at(-2).status,'completed');
 assert.equal(events.at(-1).type,'done');
});

test('cleanup failure cannot emit done after either a complete or incomplete round',async()=>{
 for (const requiresResult of [false,true]) {
  const events=[];
  const unregister=registerSessionResourceCleanup(()=>{throw new Error('fixture cleanup failed');});
  try {
   await assert.rejects(execute({...packet,requires_result:requiresResult},e=>events.push(e),()=>assert.fail(),stream([{type:'text',text:'PRESERVED_OUTPUT'}])),/Failed to cleanup session resources/);
   assert.ok(events.some(e=>e.type==='assistant'&&e.text==='PRESERVED_OUTPUT'));
   assert.ok(!events.some(e=>e.type==='completion_incomplete'));
   assert.ok(!events.some(e=>e.type==='done'));
   assert.equal(events.at(-1).type,'session_cleanup');assert.equal(events.at(-1).status,'failed');
   assert.ok(events.at(-1).elapsed_ms>=0);
  } finally {unregister();}
 }
});



test('Pi reports invalid arguments and unknown tools without exposing argument payloads',async()=>{
 const events=[];let rounds=0;
 const route={...fixtureTool('prepare_disclosure_workflow'),parameters:{type:'object',properties:{domain:{type:'string'}},required:['domain'],additionalProperties:false}};
 await execute({...packet,requires_result:false,tools:[route]},e=>events.push(e),async()=>({data:{},terminate:true}),(m,ctx,opts)=>{
  rounds++;
  return stream(rounds===1?[
   {type:'thinking',thinking:'PRIVATE_THINKING_SENTINEL'},
   {type:'toolCall',id:'invalid',name:'prepare_disclosure_workflow',arguments:{headers:'PRIVATE_HEADERS_SENTINEL',thinking:'PRIVATE_ARGUMENT_SENTINEL'}},
   {type:'toolCall',id:'missing',name:'unknown_tool',arguments:{}},
  ]:[{type:'toolCall',id:'valid',name:'prepare_disclosure_workflow',arguments:{domain:'disclosure'}}],'toolUse')(m,ctx,opts);
 });
 const failures=events.filter(e=>e.type==='tool_validation_failed');
 assert.deepEqual(failures.map(e=>e.tool),['prepare_disclosure_workflow','unknown_tool']);
 assert.match(failures[0].error,/Validation failed/);assert.match(failures[1].error,/not found/);
 assert.ok(failures.every(e=>e.phase==='working'));
 assert.ok(!JSON.stringify(events).includes('PRIVATE_'));assert.ok(!JSON.stringify(failures).includes('Received arguments'));
});

test('revision and stage handoff retain source text and all earlier drafts',async()=>{
 const events=[];let rounds=0,submissions=0;
 const submit={...fixtureTool('submit_candidate'),parameters:{type:'object',properties:{result:{type:'object',properties:{summary:{type:'string'}},required:['summary']}},required:['result']}};
 const read=fixtureTool('read_source');
 await execute({...packet,compact_workflow_context:true,stage:'assessment',requires_result:true,prompt:'ORIGINAL_TASK_RETAINED',history:[{role:'user',content:'ORIGINAL_CONSTRAINT_RETAINED',timestamp:1}],tools:[read,submit]},e=>events.push(e),async(id,name)=>{
  if(name==='read_source')return {data:{source_id:'SOURCE_ORIGINAL',page:7,text:'VERBATIM_SOURCE_DATA'}};
  if(name==='request_information')return {data:{outcome:'waiting_information'},terminate:true};
  submissions++;
  if(submissions<3)return {data:{outcome:'revise',issues:['CHECK_ISSUE_'+submissions]}};
  if(submissions===3)return {data:{outcome:'accepted',result_snapshot:{stage:'assessment',result:{summary:'ACCEPTED_CANONICAL_RESULT'}}},next_context:{system:'draft canonical upstream',system_sha256:'draft-hash',stage:'draft',requires_result:true,tools:[fixtureTool('request_information')]}};
  assert.fail('unexpected extra submission');
 },(m,ctx,opts)=>{
  rounds++;
  if([4,5,6].includes(rounds)){
   const serialized=JSON.stringify(ctx.messages);
   assert.ok(serialized.includes('ORIGINAL_TASK_RETAINED'));assert.ok(serialized.includes('ORIGINAL_CONSTRAINT_RETAINED'));
   assert.ok(serialized.includes('VERBATIM_SOURCE_DATA'));assert.ok(serialized.includes('SOURCE_ORIGINAL'));
   assert.ok(serialized.includes('REPEATED_FAILED_PROSE'));assert.ok(serialized.includes('CANDIDATE_1'));
   if(rounds>=5)assert.ok(serialized.includes('CANDIDATE_2'));
   if(rounds===6){assert.equal(ctx.systemPrompt,'draft canonical upstream');assert.ok(serialized.includes('ACCEPTED_CANONICAL_RESULT'));}

  }
  if(rounds===6)return stream([{type:'toolCall',id:'gate',name:'request_information',arguments:{}}],'toolUse')(m,ctx,opts);
  const name=rounds<=2?'read_source':'submit_candidate';
  return stream([{type:'thinking',thinking:'PRIVATE_COMPACT_THINKING'.repeat(100)},{type:'text',text:'REPEATED_FAILED_PROSE'},
   {type:'toolCall',id:'c'+rounds,name,arguments:name==='read_source'?{}:{result:{summary:'CANDIDATE_'+(rounds-2)}}}],'toolUse')(m,ctx,opts);
 });
 assert.equal(events.filter(e=>e.type==='context_compacted').length,0);
 assert.ok(events.filter(e=>e.type==='context_compacted').every(e=>e.before_chars>e.after_chars));
 assert.ok(!JSON.stringify(events).includes('PRIVATE_COMPACT_THINKING'));
 assert.equal(rounds,6);assert.equal(events.at(-1).type,'done');assert.ok(!events.some(e=>e.type==='completion_repair_started'));
});

test('workflow compaction is opt in and preserves legacy model context by default',async()=>{
 const events=[];let rounds=0;
 await execute({...packet,tools:[fixtureTool('submit_candidate')]},e=>events.push(e),async()=>({data:{outcome:'revise',issues:['fix']}}),(m,ctx,opts)=>{
  rounds++;
  if(rounds===2)assert.ok(JSON.stringify(ctx.messages).includes('LEGACY_PRIVATE_THINKING'));
  return stream(rounds===1?[{type:'thinking',thinking:'LEGACY_PRIVATE_THINKING'},{type:'toolCall',id:'s',name:'submit_candidate',arguments:{}}]:[{type:'text',text:'done'}],rounds===1?'toolUse':'stop')(m,ctx,opts);
 });
 assert.ok(!events.some(e=>e.type==='context_compacted'));
});


test('provider diagnostics retain error category and redact credentials plus provider payload fields',async()=>{
 const events=[];
 await assert.rejects(execute({...packet,headers:{'X-Auth':'HEADER_SECRET'}},e=>events.push(e),()=>assert.fail(),()=>{
  throw new Error('429 rate limit exceeded fixture-key HEADER_SECRET sk-secret123 Bearer bearerSecret\nheaders: PRIVATE_HEADERS\ntoken=PRIVATE_TOKEN\nthinking: PRIVATE_THINKING\n\nReceived arguments:\nPRIVATE_ARGUMENTS');
 }));
 const failure=events.find(e=>e.type==='provider_failure');
 assert.match(failure.message,/429 rate limit exceeded/);
 assert.ok(!JSON.stringify(events).match(/fixture-key|HEADER_SECRET|sk-secret123|bearerSecret|PRIVATE_/));
 assert.ok(!events.some(e=>e.type==='done'));
});

test('provider output truncation records a distinct failure reason',async()=>{
 const events=[];
 await assert.rejects(execute(packet,e=>events.push(e),()=>assert.fail(),stream([{type:'text',text:'partial answer'}],'length')),/output limit/);
 assert.ok(events.some(e=>e.type==='provider_failure'&&e.stopReason==='length'&&e.message.includes('output limit')));
 assert.ok(!events.some(e=>e.type==='done'));
});

test('a peer ignoring the WebSocket close frame cannot hold the completed worker open',async()=>{
 const peers=new Set();
 const server=createServer();
 server.on('upgrade',(request,socket)=>{
  peers.add(socket);socket.on('close',()=>peers.delete(socket));socket.on('error',()=>{});
  const accept=createHash('sha1').update(request.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n');
  socket.on('data',()=>{}); // Deliberately never acknowledge the close frame.
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const code=release=>`
  import {execute} from './worker.mjs';
  import {trackWorkerTransports} from './worker_resources.mjs';
  import {AssistantMessageEventStream,registerSessionResourceCleanup} from '@earendil-works/pi-ai';
  const release=trackWorkerTransports();
  const packet=${JSON.stringify({...packet,session_id:'socket-exit-test'})};
  await execute(packet,event=>process.stdout.write(JSON.stringify(event)+'\\n'),()=>{},async()=>{
   const socket=new WebSocket('ws://127.0.0.1:${server.address().port}');
   await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
   registerSessionResourceCleanup(()=>socket.close());
   const stream=new AssistantMessageEventStream();
   const message={role:'assistant',content:[{type:'text',text:'SOCKET_OUTPUT_MUST_FLUSH'}],api:packet.model.api,provider:packet.model.provider,model:packet.model.id,stopReason:'stop',timestamp:Date.now()};
   stream.push({type:'start',partial:message});stream.push({type:'done',reason:'stop',message});return stream;
  },undefined,${release?'release':'undefined'});`;
 const options={cwd:fileURLToPath(new URL('.',import.meta.url)),timeout:1000};
 try {
  await assert.rejects(promisify(execFile)(process.execPath,['--input-type=module','-e',code(false)],options),error=>{
   assert.ok(error.killed);assert.ok(error.stdout.includes('"type":"done"'));return true;
  });
  const {stdout}=await promisify(execFile)(process.execPath,['--input-type=module','-e',code(true)],options);
  const events=stdout.trim().split('\n').map(line=>JSON.parse(line));
  assert.ok(events.some(e=>e.type==='assistant'&&e.text==='SOCKET_OUTPUT_MUST_FLUSH'));
  const cleanup=events.find(e=>e.type==='transport_cleanup');
  assert.equal(cleanup.tracked_sockets,1);assert.equal(cleanup.closed_sockets,1);assert.equal(cleanup.remaining_sockets,0);
  assert.ok(Object.keys(cleanup.before).some(key=>key.includes('TCP')));
  assert.equal(events.at(-2).type,'session_cleanup');assert.equal(events.at(-1).type,'done');
 } finally {
  for(const peer of peers)peer.destroy();
  await new Promise(resolve=>server.close(resolve));
 }
});

test('closing summary retains the same selected effort and output budget',async()=>{
 let rounds=0;const events=[],tool=fixtureTool('submit_candidate');
 await execute({...packet,reasoning_effort:'max',maxTokens:8192,closing_reasoning_effort:'low',closing_max_tokens:1024,tools:[tool]},e=>events.push(e),async()=>({data:{outcome:'waiting_approval'},terminate:true,finalize:true}),(m,ctx,opts)=>{
  rounds++;assert.equal(opts.reasoning,'max');assert.equal(opts.maxTokens,8192);
  if(rounds===2){assert.equal(ctx.tools.length,0);return stream([{type:'text',text:'正文已登记，等待人工确认。'}],'stop')(m,ctx,opts);}
  return stream([{type:'toolCall',id:'save',name:'submit_candidate',arguments:{}}],'toolUse')(m,ctx,opts);
 });
 assert.equal(rounds,2);assert.ok(events.some(e=>e.type==='model_call_finished'&&e.phase==='final'&&e.reasoning_effort==='max'));
});


test('a built-in provider keeps Pi native compatibility on the real request payload',async()=>{
 const events=[];let captured;
 const originalFetch=globalThis.fetch;
 globalThis.fetch=async (url,options)=>{captured={url:String(url),headers:options?.headers,body:options?.body};
  return new Response(JSON.stringify({error:{message:'offline audit refusal'}}),{status:500,headers:{'content-type':'application/json'}});};
 const selected={...model,provider:'opencode-go',id:'deepseek-v4-flash',baseUrl:'https://opencode.ai/zen/go/v1',reasoning:true,
  thinkingLevelMap:{minimal:null,low:null,medium:null,high:'high',max:'max'},
  compat:{supportsStore:false,supportsDeveloperRole:false,maxTokensField:'max_tokens',thinkingFormat:'deepseek',requiresReasoningContentOnAssistantMessages:true}};
 try{
  await assert.rejects(execute({...packet,model:selected,reasoning_effort:'high'},e=>events.push(e),()=>assert.fail()));
 }finally{globalThis.fetch=originalFetch;}
 const body=JSON.parse(captured.body);
 assert.equal(captured.url,'https://opencode.ai/zen/go/v1/chat/completions');
 assert.equal(body.model,'deepseek-v4-flash');assert.equal(body.max_tokens,1024);assert.equal(body.max_completion_tokens,undefined);
 assert.deepEqual(body.thinking,{type:'enabled'});assert.equal(body.reasoning_effort,'high');
 assert.ok(events.some(e=>e.type==='provider_failure'));
});

test('output defaults respect the model and preserve explicit request limits',async()=>{
 for(const [selected,explicit,expected] of [[{...model,maxTokens:32000},undefined,32000],[model,8192,8192],[{...model,maxTokens:undefined},undefined,16384]]){
  let limit;
  await execute({...packet,model:selected,maxTokens:explicit},()=>{},()=>assert.fail(),(m,ctx,options)=>{
   limit=options.maxTokens;return stream([{type:'text',text:'offline'}])(m,ctx,options);
  });
  assert.equal(limit,expected);
 }
});

test('provider request uses native retry defaults',async()=>{await execute(packet,()=>{},()=>assert.fail(),(m,c,o)=>{assert.equal(o.maxRetries,undefined);return stream([{type:'text',text:'ok'}])(m,c,o);});});

test('external cancellation interrupts an immediately repeating tool loop',async()=>{
 const cancel=new AbortController();let calls=0;
 const timer=setTimeout(()=>cancel.abort(),20);
 try {
  await assert.rejects(execute({...packet,tools:[fixtureTool('read_source')]},()=>{},async()=>{calls++;return {data:{}};},
   (m,c,o)=>stream([{type:'toolCall',id:'repeat-'+calls,name:'read_source',arguments:{}}],'toolUse')(m,c,o),cancel.signal),/Cancelled/);
  assert.ok(calls>0);
 } finally {clearTimeout(timer);}
});
