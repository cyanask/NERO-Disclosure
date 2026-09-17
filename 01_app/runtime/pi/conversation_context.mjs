import {compact,prepareCompaction,createCompactionSummaryMessage,convertToLlm,BACKGROUND_CONTEXT,withAbortSignal} from '@earendil-works/pi-agent-core';
import {estimateContextTokens} from '@earendil-works/pi-ai/utils/estimate';
import {cleanupSessionResources} from '@earendil-works/pi-ai';
import {mkdirSync,writeFileSync,renameSync,unlinkSync} from 'node:fs';
import {dirname} from 'node:path';
import {randomUUID} from 'node:crypto';

// Replay is private, belongs to one run and is covered by the existing pi-runs
// deletion/backup lifecycle. Public journals never contain this checkpoint.
export function conversationCheckpoint(packet){
 const secrets=new Set();
 const clean=value=>{
  if(typeof value==='string'){for(const secret of secrets)value=value.split(secret).join('[REDACTED]');return value;}
  if(Array.isArray(value))return value.map(clean);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,clean(v)]));
  return value;
 };
 return (messages,archive=false)=>{
  if(!packet.context_state_path)return;
  for(const value of [packet.apiKey,...Object.values(packet.headers||{}),...Object.values(packet.providerEnv||{})])if(typeof value==='string'&&value)secrets.add(value);
  const path=archive?packet.context_state_path+'.before-'+randomUUID()+'.json':packet.context_state_path;
  const temporary=path+'.'+randomUUID()+'.tmp';
  const safe=messages.filter(m=>!(m.role==='assistant'&&['error','aborted','pending'].includes(m.stopReason))).map(message=>{
   const {errorMessage,...value}=message;
   return clean({...value,...(Array.isArray(value.content)?{content:value.content.filter(block=>block.type!=='thinking')}:{})});
  });
  const data={schema:1,session_id:packet.session_id,run_id:packet.run_id,model:packet.model.id,provider:packet.model.provider,messages:safe};
  mkdirSync(dirname(path),{recursive:true,mode:0o700});
  try{writeFileSync(temporary,JSON.stringify(data),{flag:'wx',mode:0o600});renameSync(temporary,path);}
  catch(error){try{unlinkSync(temporary);}catch{}throw error;}
 };
}

export function createConversationCompactor(packet,request,emit,checkpoint){
 return async(context,signal)=>{
  if(!packet.manage_context)return context.messages;
  const model=packet.model,window=model.contextWindow;
  const reserve=Math.min(16384,Math.max(1024,Math.floor(window*0.15)));
  const estimate=messages=>estimateContextTokens({...context,messages:convertToLlm(messages)}).tokens;
  const before=estimate(context.messages);
  if(before<=window-reserve)return context.messages;
  if(context.messages.length<=1||estimate([])>window-reserve)throw new Error('Current request or authoritative context exceeds model capacity; original input retained');
  const entries=context.messages.map((message,index)=>({id:String(index),parentId:index?String(index-1):null,seq:index,timestamp:message.timestamp,
   ...(message.role==='compactionSummary'?{type:'compaction',summary:message.summary,retainedTail:[],tokensBefore:message.tokensBefore,fromHook:false}:{type:'message',message})}));
  const preparation=prepareCompaction(entries,{enabled:true,reserveTokens:reserve,keepRecentTokens:Math.min(20000,Math.floor(window*0.25))});
  if(!preparation.ok||!preparation.value)throw new Error('Context compaction could not prepare a safe message boundary');
  checkpoint(context.messages,true);
  emit({type:'context_compaction_started',tokens_before:before});
  // Use Pi's own cut points, prompts and summary merger, through the same scoped
  // provider transport. This does not run business tools or adopt new evidence.
  const summaryModel={completeSimple:async(model,summaryContext,options)=>{
   const maxTokens=Math.min(options.maxTokens??model.maxTokens,packet.maxTokens??model.maxTokens);
   try{
    const response=await (await request(model,summaryContext,{...options,maxTokens,signal})).result();
    if(response.stopReason!=='stop'||!response.content.some(item=>item.type==='text'&&item.text.trim()))throw new Error('Context summary incomplete; original history retained');
    return response;
   }finally{cleanupSessionResources(options.sessionId);}
  }};
  const result=await compact(preparation.value,summaryModel,model,
   '保留用户约束、未完成任务、已执行动作、失败原因、来源定位、金额单位及期间。明确区分用户确认与模型建议。摘要只是历史线索，不能替代当前系统提供的事实、证据和审批状态。',
   packet.reasoning_effort||'off',undefined,undefined,signal?withAbortSignal(signal,BACKGROUND_CONTEXT):BACKGROUND_CONTEXT);
  if(!result.ok)throw new Error('Context compaction failed; original history retained');
  const next=[createCompactionSummaryMessage(result.value.summary,result.value.tokensBefore,Date.now()),...result.value.retainedTail];
  const after=estimate(next);
  if(after>=before||after>window-reserve)throw new Error('Context remains too large after compaction; original history retained');
  emit({type:'context_compacted',reason:'pi_native_capacity',tokens_before:before,tokens_after:after,before_chars:JSON.stringify(context.messages).length,after_chars:JSON.stringify(next).length});
  return next;
 };
}
