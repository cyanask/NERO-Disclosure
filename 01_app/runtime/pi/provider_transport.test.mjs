import test from 'node:test';
import assert from 'node:assert/strict';
import {execute} from './worker.mjs';
import {control} from './model_control.mjs';
import {providerById} from './provider_runtime.mjs';
import {modelStream} from './model_transport.mjs';
import contract from '../../config/model-contract.json' with {type:'json'};
import {authInteraction} from './auth_interaction.mjs';

const packet={system:'Transport fixture',history:[],prompt:'Reply OK',apiKey:'synthetic-key',
 tools:[],session_id:'conversation-a',maxTokens:512};
const go=()=>providerById('opencode-go').getModels().find(m=>m.id==='deepseek-v4.1-flash');

// Capture the HTTP request after Pi's real protocol adapters and SDKs serialize it.
// No credentials, provider network or business data are used.
async function capture(run,respond){
 const requests=[],original=globalThis.fetch;
 globalThis.fetch=async(url,options)=>{
  const request={url:String(url),headers:new Headers(options.headers),body:JSON.parse(options.body)};
  requests.push(request);
  return respond?respond(request,requests.length):new Response(JSON.stringify({error:{message:'offline refusal'}}),
   {status:400,headers:{'content-type':'application/json'}});
 };
 try{await run(requests);}finally{globalThis.fetch=original;}
 return requests;
}
function completion(delta,finish_reason){
 return new Response('data: '+JSON.stringify({id:'fixture',object:'chat.completion.chunk',
  choices:[{index:0,delta,finish_reason}]})+'\n\ndata: [DONE]\n\n',
  {headers:{'content-type':'text/event-stream'}});
}

test('OpenCode native adapters carry conversation identity across all three protocols',async()=>{
 for(const providerId of ['opencode-go','opencode'])for(const api of ['openai-completions','openai-responses','anthropic-messages']){
  const provider=providerById(providerId);
  const native=provider.getModels().find(m=>m.api===api);
  // A supported API can be used by a newly discovered model absent from the native catalog.
  const model=native||{...go(),provider:providerId,api};
  const events=[];
  const requests=await capture(async()=>assert.rejects(execute({...packet,model},e=>events.push(e),()=>assert.fail())));
  assert.equal(requests.length,1);
  assert.equal(requests[0].headers.get('x-opencode-session'),packet.session_id,providerId+'/'+api);
  assert.equal(requests[0].headers.get('x-opencode-client'),'nero-disclosure');
  assert.match(requests[0].headers.get('user-agent'),/nero-disclosure/i);
  assert.ok(events.some(e=>e.type==='provider_failure'));
  assert.ok(!events.some(e=>e.type==='done'));
 }
});

test('native DeepSeek tool replay, a new round and the connection probe retain the right session',async()=>{
 const tool={name:'read_source',description:'Read synthetic source',parameters:{type:'object',properties:{},additionalProperties:false}};
 const events=[];
 const requests=await capture(async()=>{
  await execute({...packet,model:go(),reasoning_effort:'high',tools:[tool]},e=>events.push(e),async()=>({data:{ok:true}}));
  await execute({...packet,model:go()},()=>{},()=>assert.fail());
  const result=await control({operation:'probe',packet:{...packet,model:go(),session_id:'connection-probe'}},()=>{});
  assert.equal(result.status,'passed');
  await execute({...packet,model:go(),session_id:'conversation-b'},()=>{},()=>assert.fail());
 },(_,number)=>number===1?completion({role:'assistant',reasoning_content:'synthetic reasoning',
  tool_calls:[{index:0,id:'call_1',type:'function',function:{name:'read_source',arguments:'{}'}}]},'tool_calls'):
  completion({role:'assistant',content:'OK'},'stop'));
 assert.deepEqual(requests.map(r=>r.headers.get('x-opencode-session')),
  ['conversation-a','conversation-a','conversation-a','connection-probe','conversation-b']);
 assert.equal(requests[0].body.model,'deepseek-v4.1-flash');
 assert.equal(requests[0].body.max_tokens,512);
 assert.deepEqual(requests[0].body.thinking,{type:'enabled'});
 assert.equal(requests[0].body.reasoning_effort,'high');
 assert.equal(requests[1].body.messages.find(m=>m.role==='assistant').reasoning_content,'synthetic reasoning');
 assert.ok(requests[1].body.messages.some(m=>m.role==='tool'));
 assert.equal(events.at(-1).type,'done');
 assert.ok(!JSON.stringify(events).includes('synthetic reasoning'));
});

test('OpenCode endpoint aliases receive identity while unrelated and lookalike hosts do not',async()=>{
 for(const [baseUrl,expected] of [['https://opencode.ai/zen/go/v1',true],['https://opencode.ai.evil.invalid/v1',false],['https://example.invalid/v1',false]]){
  const requests=await capture(async()=>assert.rejects(execute({...packet,model:{...go(),provider:'custom-route',baseUrl}},()=>{},()=>assert.fail())));
  assert.equal(requests[0].headers.get('x-opencode-session'),expected?packet.session_id:null);
 }
});

test('OpenCode missing session fails before transport; private auth headers survive case-insensitive merging',async()=>{
 const events=[];
 const requests=await capture(async()=>{
  await assert.rejects(execute({...packet,model:go(),session_id:undefined},e=>events.push(e),()=>assert.fail()));
 });
 assert.equal(requests.length,0);
 assert.ok(events.some(e=>e.type==='provider_failure'&&/session ID/.test(e.message)));
 const authorized=await capture(async()=>assert.rejects(execute({...packet,model:go(),headers:{
  'X-OpenCode-Session':'stale-id','X-Private-Auth':'synthetic-auth'}},()=>{},()=>assert.fail())));
 assert.equal(authorized[0].headers.get('x-opencode-session'),packet.session_id);
 assert.equal(authorized[0].headers.get('x-private-auth'),'synthetic-auth');
});

test('an explicit API override changes the actual endpoint even under a native provider ID',async()=>{
 const requests=await capture(async()=>assert.rejects(execute({...packet,model:{...go(),provider:'openai',api:'openai-completions',baseUrl:'https://example.invalid/v1'}},()=>{},()=>assert.fail())));
 assert.equal(requests[0].url,'https://example.invalid/v1/chat/completions');
 assert.ok(requests[0].body.messages);assert.equal(requests[0].body.input,undefined);
});

test('every advertised API has a real Pi custom transport',async()=>{
 for(const {id} of contract.apis)assert.equal(typeof await modelStream({api:id}), 'function',id);
 const emptyDynamic={getModels:()=>[],refreshModels:()=>{},streamSimple:()=>assert.fail('An empty dynamic catalog cannot override the declared API')};
 assert.notEqual(await modelStream({api:'openai-completions'},emptyDynamic),emptyDynamic.streamSimple);
 await assert.rejects(modelStream({api:'../escape'}),/Unsupported/);
});

test('native login prompts are answered privately and callback cancellation clears them',async()=>{
 const events=[],answers=new Map(),abort=new AbortController();
 const interaction=authInteraction(e=>events.push(e),abort.signal,answers);
 const pending=interaction.prompt({type:'secret',message:'Code'});
 const id=events.at(-1).id;answers.get(id).resolve('private-code');answers.delete(id);
 assert.equal(await pending,'private-code');assert.ok(!JSON.stringify(events).includes('private-code'));
 const callback=new AbortController();
 const cancelled=interaction.prompt({type:'manual_code',message:'Code',signal:callback.signal});
 callback.abort();await assert.rejects(cancelled,/cancelled/);
 assert.equal(answers.size,0);assert.equal(events.at(-1).type,'auth_prompt_cancelled');
});
