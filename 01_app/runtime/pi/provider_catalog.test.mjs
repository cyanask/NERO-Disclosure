import test from 'node:test';
import assert from 'node:assert/strict';
import {control,catalog} from './model_control.mjs';
import {builtinProviders} from '@earendil-works/pi-ai/providers/all';
import {resolveCredential} from './provider_runtime.mjs';
import {execute} from './worker.mjs';
import contract from '../../config/model-contract.json' with {type:'json'};

const credential={type:'api_key',key:'synthetic-provider-fixture'};
const packet={operation:'models',provider:'opencode-go',credential};

test('subscription OAuth uses Pi native availability instead of API-key model discovery',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async()=>assert.fail('OAuth catalog must not call an API-key /models endpoint');
 try{
  const result=await control({operation:'models',provider:'anthropic',credential:{type:'oauth',access:'synthetic-access',refresh:'synthetic-refresh',expires:Date.now()+3600000}});
  assert.equal(result.source,'pi_builtin');assert.ok(result.models.length>0);
  assert.ok(!JSON.stringify(result).includes('synthetic-access'));
 }finally{globalThis.fetch=original;}
});

test('scoped cloud auth is resolved without importing host credentials',async()=>{
 const aws=await resolveCredential({provider:'amazon-bedrock',credential:{type:'api_key',env:{AWS_PROFILE:'isolated-profile',AWS_REGION:'us-west-2'}}});
 assert.deepEqual(aws.auth,{});assert.equal(aws.env.AWS_PROFILE,'isolated-profile');
 const azure=await resolveCredential({provider:'azure-openai-responses',credential:{type:'api_key',key:'synthetic-key',env:{AZURE_OPENAI_RESOURCE_NAME:'isolated-resource'}}});
 assert.equal(azure.env.AZURE_OPENAI_RESOURCE_NAME,'isolated-resource');
});
const response=body=>new Response(JSON.stringify(body),{headers:{'content-type':'application/json'}});
async function mockedFetch(fetcher,run){const original=globalThis.fetch;globalThis.fetch=fetcher;try{return await run();}finally{globalThis.fetch=original;}}

test('all native providers remain discoverable without reading account credentials',()=>{
 assert.deepEqual(catalog().providers.map(p=>p.id),builtinProviders().map(p=>p.id));
});

test('shared protocol vocabulary covers the installed native model APIs',async()=>{
 const apis=new Set(contract.apis.map(item=>item.id));
 for(const provider of builtinProviders())for(const model of provider.getModels())assert.ok(apis.has(model.api),model.api);
 for(const api of apis)await import('@earendil-works/pi-ai/api/'+api);
 assert.deepEqual(contract.defaults,{contextWindow:128000,maxTokens:16384,reasoning:false,input:['text']});
});

test('official DeepSeek 4.1 ID has an exact model contract, without inferred aliases',async()=>{
 const result=await mockedFetch(async()=>response({data:[{id:'deepseek-v4.1-flash'},{id:'deepseek-flash'}]}),()=>control(packet,()=>{}));
 const exact=result.models.find(model=>model.id==='deepseek-v4.1-flash');
 assert.equal(exact.label,'DeepSeek V4.1 Flash');assert.equal(exact.catalog,true);
 assert.equal(exact.baseUrl,'https://opencode.ai/zen/go/v1');assert.equal(exact.contextWindow,1000000);
 assert.equal(exact.compat.requiresReasoningContentOnAssistantMessages,true);
 assert.equal(result.models.find(model=>model.id==='deepseek-flash').catalog,false);
});

test('cloud list preserves native compat and new IDs using documented Pi loading defaults',async()=>{
 const result=await mockedFetch(async(url,options)=>{
  assert.equal(url,'https://opencode.ai/zen/go/v1/models');assert.equal(options.redirect,'error');
  assert.equal(options.headers.Authorization,'Bearer '+credential.key);
  return response({data:[{id:'deepseek-v4-flash'},{id:'new-text',context_length:65536,max_output_tokens:2048,architecture:{input_modalities:['text','image']}},{id:'new-text'},{id:'unknown-only'}]});
 },()=>control(packet,()=>{},new AbortController().signal));
 assert.equal(result.status,'ok');assert.equal(result.models.length,3);
 assert.equal(result.models.find(m=>m.id==='new-text').contextWindow,65536);
 const known=result.models.find(m=>m.id==='deepseek-v4-flash');
 assert.equal(known.compat.thinkingFormat,'deepseek');assert.ok(known.thinking_levels.includes('max'));
 const unknown=result.models.find(m=>m.id==='unknown-only');
 assert.equal(unknown.catalog,false);assert.equal(unknown.api,'openai-completions');assert.equal(unknown.contextWindow,128000);
 assert.equal(unknown.maxTokens,16384);assert.equal(unknown.reasoning,false);assert.deepEqual(unknown.thinking_levels,['off']);
 assert.ok(!JSON.stringify(result).includes(credential.key));
});

test('cloud metadata is retained instead of replacing it with fixed 128K defaults',async()=>{
 const result=await mockedFetch(async()=>response({data:[{id:'new-model',context_length:32768,max_output_tokens:4096,reasoning:true,architecture:{input_modalities:['text']}}]}),()=>control(packet,()=>{}));
 const row=result.models[0];assert.equal(row.id,'new-model');assert.equal(row.contextWindow,32768);assert.equal(row.maxTokens,4096);assert.equal(row.reasoning,true);assert.deepEqual(row.input,['text']);
});

test('complete paginated model lists are deduplicated and failures never return a partial success',async()=>{
 let count=0;
 const result=await mockedFetch(async url=>{
  count++;if(count===1)return response({data:[{id:'first'}],has_more:true,last_id:'first'});
  assert.equal(new URL(url).searchParams.get('after_id'),'first');return response({data:[{id:'first'},{id:'second'}],has_more:false});
 },()=>control(packet,()=>{}));
 assert.equal(result.status,'ok');assert.deepEqual(result.models.map(m=>m.id),['first','second']);
 count=0;
 const failed=await mockedFetch(async()=>++count===1?response({data:[{id:'first'}],has_more:true,last_id:'first'}):new Response('',{status:503}),()=>control(packet,()=>{}));
 assert.equal(failed.status,'failed');assert.equal(failed.models,undefined);
});

test('malformed, oversized, redirect, unauthorized and aborted lists fail without secrets',async()=>{
 for(const fetcher of [async()=>response({error:'bad'}),async()=>new Response('x'.repeat(2000001)),async()=>new Response('',{status:302}),async()=>new Response(credential.key,{status:401}),async()=>{throw new Error('private '+credential.key);}]){
  const result=await mockedFetch(fetcher,()=>control(packet,()=>{}));
  assert.equal(result.status,'failed');assert.ok(!JSON.stringify(result).includes(credential.key));
 }
 const controller=new AbortController();controller.abort();
 const result=await mockedFetch(async()=>{throw new Error('aborted');},()=>control(packet,()=>{},controller.signal));
 assert.equal(result.status,'failed');
});

test('empty authoritative cloud inventory is a successful empty list, not invented static availability',async()=>{
 const result=await mockedFetch(async()=>response({data:[]}),()=>control(packet,()=>{}));
 assert.equal(result.status,'ok');assert.deepEqual(result.models,[]);
});

test('a provider without a model-list endpoint uses its complete Pi native directory',async()=>{
 const result=await mockedFetch(async()=>new Response('',{status:404}),()=>control(packet,()=>{}));
 assert.equal(result.status,'ok');assert.equal(result.source,'pi_builtin');
 assert.ok(result.models.length>1);assert.ok(result.models.some(model=>model.id==='deepseek-v4.1-flash'));
});

test('native auth plus provider stream materializes Cloudflare endpoint and dedicated headers',async()=>{
 const env={CLOUDFLARE_ACCOUNT_ID:'account-fixture',CLOUDFLARE_GATEWAY_ID:'gateway-fixture'};
 const model={id:'gpt-4o',name:'fixture',provider:'cloudflare-ai-gateway',api:'openai-completions',baseUrl:'https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/openai',reasoning:false,input:['text'],contextWindow:128000,maxTokens:1024,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
 const resolved=await resolveCredential({provider:model.provider,model,credential:{...credential,env}});
 assert.equal(resolved.auth.headers.Authorization,null);assert.deepEqual(resolved.env,env);
 let captured;
 await mockedFetch(async(url,options)=>{captured={url:String(url),headers:new Headers(options.headers)};return new Response('{"error":{"message":"synthetic refusal"}}',{status:400});},async()=>{
  await assert.rejects(execute({model,apiKey:credential.key,headers:resolved.auth.headers,providerEnv:resolved.env,system:'offline',history:[],prompt:'offline',tools:[],session_id:'cf-fixture'},()=>{},()=>assert.fail()));
 });
 assert.equal(captured.url,'https://gateway.ai.cloudflare.com/v1/account-fixture/gateway-fixture/openai/chat/completions');
 assert.equal(captured.headers.get('cf-aig-authorization'),'Bearer '+credential.key);
 assert.equal(captured.headers.get('authorization'),null);
});

test('native compatibility is hydrated even for an existing profile without compat',async()=>{
 const native=builtinProviders().find(p=>p.id==='opencode-go').getModels().find(m=>m.id==='deepseek-v4-flash');
 const {compat,...model}=native;let body;
 await mockedFetch(async(url,options)=>{body=JSON.parse(options.body);return new Response('{"error":{"message":"synthetic refusal"}}',{status:400});},async()=>{
  await assert.rejects(execute({model,apiKey:credential.key,system:'offline',history:[],prompt:'offline',reasoning_effort:'high',maxTokens:1024,tools:[],session_id:'native-fixture'},()=>{},()=>assert.fail()));
 });
 assert.equal(body.max_tokens,1024);assert.equal(body.max_completion_tokens,undefined);
 assert.deepEqual(body.thinking,{type:'enabled'});
});
