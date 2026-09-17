import {getSupportedThinkingLevels} from '@earendil-works/pi-ai';
import {providerById,providerSession,endpoint} from './provider_runtime.mjs';
import contract from '../../config/model-contract.json' with {type:'json'};

export const APIS=new Set(contract.apis.map(item=>item.id));
export const descriptor=model=>({id:model.id,label:model.name,api:model.api,baseUrl:model.baseUrl,reasoning:!!model.reasoning,
 thinking_levels:getSupportedThinkingLevels(model),thinking_level_map:model.thinkingLevelMap||{},contextWindow:model.contextWindow,
 maxTokens:model.maxTokens,input:model.input,compat:model.compat||{},catalog:true});
const MAX_BYTES=2000000,MAX_MODELS=5000,MAX_PAGES=25;

function discovery(provider,resolution){
 const known=provider.getModels();
 let sample=known.find(model=>model.baseUrl&&['openai-completions','openai-responses'].includes(model.api));
 let kind='openai',base=sample?.baseUrl||provider.baseUrl;
 if(provider.id.startsWith('cloudflare-'))throw new Error('unsupported'); // Their list endpoints differ from inference routes.
 if(!sample){
  sample=known.find(model=>['anthropic-messages','google-generative-ai'].includes(model.api));
  if(!sample)throw new Error('unsupported');
  kind=sample.api==='anthropic-messages'?'anthropic':'google';base=sample.baseUrl||provider.baseUrl;
 }
 base=endpoint(resolution.auth.baseUrl||base,resolution.env);
 if(!base||/[{}]/.test(base))throw new Error('unsupported');
 const url=new URL(base.endsWith('/')?base:base+'/');
 if(url.protocol!=='https:'||url.username||url.password)throw new Error('unsupported');
 if(kind==='anthropic'&&!url.pathname.replace(/\/$/,'').endsWith('/v1'))url.pathname+='v1/';
 url.pathname+='models';
 const key=resolution.auth.apiKey;
 const headers={Accept:'application/json',...(kind==='google'?{'x-goog-api-key':key}:kind==='anthropic'?{'x-api-key':key,'anthropic-version':'2023-06-01'}:{Authorization:'Bearer '+key})};
 for(const [name,value] of Object.entries(resolution.auth.headers||{})){
  for(const existing of Object.keys(headers))if(existing.toLowerCase()===name.toLowerCase())delete headers[existing];
  if(value!==null)headers[name]=value;
 }
 for(const name of Object.keys(headers))if(headers[name]===undefined)delete headers[name];
 return {url,headers,kind,api:sample.api,baseUrl:sample.baseUrl||provider.baseUrl};
}

async function boundedJson(response,budget){
 const declared=Number(response.headers.get('content-length')||0);
 if(declared>MAX_BYTES-budget.used)throw new Error('oversized');
 const reader=response.body?.getReader();if(!reader)throw new Error('format');
 const chunks=[];
 try{
  while(true){const {value,done}=await reader.read();if(done)break;budget.used+=value.byteLength;
   if(budget.used>MAX_BYTES)throw new Error('oversized');chunks.push(value);}
 }finally{await reader.cancel().catch(()=>{});}
 try{return JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw new Error('format');}
}

// Pi coding-agent's modelFromJson defaults for an ID-only model: provider API/base URL,
// reasoning=false, text input, 128000 context and 16384 output. These are loading defaults,
// not claims about an upstream's undocumented capabilities. No human confirmation gate.
// Source: @earendil-works/pi-coding-agent 0.85.1, core/provider-composer.js.
export function cloudDescriptor(row,id,defaults){
 const value=typeof row==='object'&&row!==null?row:{};
 const result={id,label:String(value.name||value.displayName||value.label||id).slice(0,100),catalog:false,api:defaults.api,baseUrl:defaults.baseUrl,
  ...contract.defaults,input:[...contract.defaults.input],compat:{},definition_source:'pi_custom_defaults'};
 if(typeof value.api==='string'&&APIS.has(value.api))result.api=value.api;
 const context=value.contextWindow??value.context_length??value.inputTokenLimit;
 const maximum=value.maxTokens??value.max_output_tokens??value.outputTokenLimit;
 if(Number.isSafeInteger(context)&&context>0)result.contextWindow=context;
 if(Number.isSafeInteger(maximum)&&maximum>0)result.maxTokens=maximum;
 if(typeof value.reasoning==='boolean')result.reasoning=value.reasoning;
 const input=value.input??value.architecture?.input_modalities;
 if(Array.isArray(input))result.input=input.filter(x=>['text','image','audio','video'].includes(x));
 result.thinking_levels=getSupportedThinkingLevels({...result,name:result.label,provider:defaults.provider});
 result.thinking_level_map={};
 return result;
}

export function cachedProviderModels(providerId,rows){
 const provider=providerById(providerId);if(!provider||!Array.isArray(rows))throw new Error('format');
 const native=provider.getModels(),known=new Map(native.map(model=>[model.id,model]));
 const fallback=native.find(model=>model.api==='openai-completions')||native[0];
 if(!fallback)throw new Error('unsupported');
 return rows.map(row=>{
  if(typeof row?.id!=='string'||!row.id.trim())throw new Error('format');
  return known.has(row.id)?descriptor(known.get(row.id)):cloudDescriptor(row,row.id,{provider:providerId,api:fallback.api,baseUrl:fallback.baseUrl||provider.baseUrl});
 });
}

export async function providerModels(packet,parentSignal){
 const provider=providerById(packet.provider);if(!provider)throw new Error('unsupported');
 const signal=parentSignal?AbortSignal.any([parentSignal,AbortSignal.timeout(20000)]):AbortSignal.timeout(20000);
 const {models,credentials}=await providerSession(provider,packet.credential);
 const resolution=await models.getAuth(provider.id);if(!resolution)throw new Error('unauthorized');
 const currentCredential=await credentials.read(provider.id);
 const authorized=packet.credential?.type==='oauth'&&JSON.stringify(currentCredential)!==JSON.stringify(packet.credential)?{credential:currentCredential}:{};
 if(packet.credential?.type==='oauth'&&!provider.refreshModels){
  // Subscription OAuth is not an API-key /models contract. Pi owns which
  // native models are available to this credential, including provider filters.
  return {...authorized,source:'pi_builtin',endpoint:'',models:(await models.getAvailable(provider.id)).map(descriptor)};
 }
 if(provider.refreshModels){
  const refreshed=await models.refresh({allowNetwork:true,force:true,signal});
  if(refreshed.aborted||signal.aborted)throw new Error('timeout');
  if(refreshed.errors.size)throw new Error('rejected');
  const available=await models.getAvailable(provider.id);
  if(available.length>MAX_MODELS)throw new Error('oversized');
  return {...authorized,source:'provider_refresh',endpoint:'',models:available.map(descriptor)};
 }
 let request;
 try{request=discovery(provider,resolution);}
 catch(error){
  if(error.message!=='unsupported')throw error;
  // A provider with no live-list API still exposes all of Pi's native models.
  // This is a native catalog result, never claimed to be an account-specific cloud reply.
  return {...authorized,source:'pi_builtin',endpoint:'',models:(await models.getAvailable(provider.id)).map(descriptor)};
 }
 const initial=request.url.toString();
 const known=new Map(provider.getModels().map(model=>[model.id,model]));
 const found=new Map(),visited=new Set(),budget={used:0};let url=initial;
 for(let page=0;url;page++){
  if(page>=MAX_PAGES||visited.has(url))throw new Error('pagination');visited.add(url);
  let response;
  try{response=await fetch(url,{headers:request.headers,signal,redirect:'error'});}
  catch{throw new Error(signal.aborted?'timeout':'unreachable');}
  if(response.status===401||response.status===403)throw new Error('unauthorized');
  if(page===0&&(response.status===404||response.status===405))return {...authorized,source:'pi_builtin',endpoint:'',models:(await models.getAvailable(provider.id)).map(descriptor)};
  if(!response.ok)throw new Error('rejected');
  const body=await boundedJson(response,budget);
  const rows=Array.isArray(body)?body:body?.data??body?.models;
  if(!Array.isArray(rows))throw new Error('format');
  for(const row of rows){
   const raw=typeof row==='string'?row:row?.id??(request.kind==='google'?row?.name:undefined);
   if(typeof raw!=='string'||!raw.trim()||raw.length>160||/[\u0000-\u001f]/.test(raw))throw new Error('format');
   const id=request.kind==='google'?raw.replace(/^models\//,''):raw;
   if(!found.has(id))found.set(id,known.has(id)?descriptor(known.get(id)):cloudDescriptor(row,id,{...request,provider:provider.id}));
   if(found.size>MAX_MODELS)throw new Error('oversized');
  }
  const next=new URL(initial);url='';
  if(body?.nextPageToken){next.searchParams.set('pageToken',String(body.nextPageToken));url=next.toString();}
  else if(body?.has_more){
   const cursor=body.last_id??rows.at(-1)?.id;
   if(typeof cursor!=='string'||!cursor)throw new Error('pagination');
   next.searchParams.set('after_id',cursor);url=next.toString();
  }else if(body?.next||body?.next_cursor){throw new Error('pagination');} // Never claim a partial unhandled list is complete.
 }
 return {...authorized,source:'endpoint',endpoint:initial,models:[...found.values()]};
}

export const LIST_REASONS={unauthorized:'供应商授权不完整或拒绝了该密钥',unreachable:'无法连接供应商接口',rejected:'供应商未接受模型列表请求',
 format:'模型列表格式不受支持',unsupported:'该供应商尚无可用的云端目录适配，请使用 Pi 内置目录',
 oversized:'模型列表超过读取上限，保留原配置',pagination:'模型列表分页尚未完整读取，保留原配置',timeout:'云端模型读取超时，保留原配置'};
