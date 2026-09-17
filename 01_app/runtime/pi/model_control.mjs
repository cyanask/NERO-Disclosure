// Pi's provider catalog and OAuth implementation; private results go only to the
// owning Python pipe. This command is never used as a user-facing CLI or log.
import {getBuiltinModelDataGeneratedAt} from '@earendil-works/pi-ai/providers/all';
import {createInterface} from 'node:readline';
import {pathToFileURL} from 'node:url';
import {execute} from './worker.mjs';
import {resolveCredential,credentialFields,runtimeProviders,providerSession,PI_VERSION} from './provider_runtime.mjs';
import {descriptor,providerModels,cachedProviderModels,LIST_REASONS} from './provider_catalog.mjs';
import {authInteraction} from './auth_interaction.mjs';

export function catalog(){
 return {version:PI_VERSION,generated_at:getBuiltinModelDataGeneratedAt(),source:'pi_builtin',providers:runtimeProviders().map(provider=>({
  id:provider.id,name:provider.name,baseUrl:provider.baseUrl,
  auth_types:[...(provider.auth.apiKey?['api_key']:[]),...(provider.auth.oauth?['oauth']:[])],
  dynamic:!!provider.refreshModels,credential_fields:credentialFields(provider.id),
  models:provider.getModels().map(descriptor),
 }))};
}
export async function control(packet,emit,signal,interaction){
 if(packet.operation==='catalog')return catalog();
 if(packet.operation==='resolve')return resolveCredential(packet);
 if(packet.operation==='models_cached')return {status:'ok',source:'saved_cloud',models:cachedProviderModels(packet.provider,packet.models)};
 if(packet.operation==='models'){
  try{return {status:'ok',...(await providerModels(packet,signal))};}
  catch(error){return {status:'failed',reason:LIST_REASONS[error?.message]||'连接或接口异常'};}
 }
 if(packet.operation==='probe'){
  const rows=[];
  await execute(packet.packet,event=>rows.push(event),async()=>{throw new Error('Probe has no tools');},undefined,signal);
  const started=rows.find(row=>row.type==='started'),answers=rows.filter(row=>row.type==='assistant'),answer=answers.at(-1),reply=answers.map(row=>row.text).join('');
  if(!started||!answer||answer.model!==started.model||answer.provider!==started.provider||!rows.some(row=>row.type==='done')||!reply.trim())throw new Error('Incomplete or mismatched probe');
  return {status:'passed',model:answer.model,provider:answer.provider,reasoning_effort:started.reasoning_effort,reply:reply.slice(0,1000),scope:'核对所选配置、Pi 响应和完整短请求；不证明远端内部路由或业务效果'};
 }
 const provider=runtimeProviders().find(value=>value.id===packet.provider);
 if(!provider)throw new Error('Provider not registered');
 const {models,credentials}=await providerSession(provider,packet.credential);
 if(packet.operation==='login'){
  if(!provider.auth.oauth)throw new Error('Provider has no OAuth flow');
  await models.login(provider.id,'oauth',{
   ...interaction,signal,
   prompt:async prompt=>{
    if(provider.id==='openai-codex'&&prompt.type==='select'&&prompt.options.some(option=>option.id==='device_code'))return 'device_code';
    if(!interaction)throw new Error('Login interaction is required');
    return interaction.prompt(prompt);
   },
   notify:event=>{
    if(event.type==='device_code')emit({type:'device_code',user_code:event.userCode,url:event.verificationUri,expires_in:event.expiresInSeconds});
    if(event.type==='auth_url')emit({type:'auth_url',url:event.url,instructions:event.instructions});
    // Raw provider progress/error messages may contain auth response payloads.
   },
  });
  return {credential:await credentials.read(provider.id)};
 }
 throw new Error('Unsupported operation');
}
async function main(){
 const lines=createInterface({input:process.stdin,crlfDelay:Infinity}),abort=new AbortController(),answers=new Map();let started=false,finished=false;
 process.on('SIGTERM',()=>abort.abort());
 lines.on('close',()=>{if(started&&!finished)abort.abort();});
 lines.on('line',line=>{
  let packet;try{packet=JSON.parse(line);}catch{process.exitCode=1;lines.close();return;}
  if(started){
   if(packet.type==='auth_response'&&typeof packet.value==='string'&&packet.value.length<=16384){const pending=answers.get(packet.id);if(pending){answers.delete(packet.id);pending.resolve(packet.value);}}
   return;
  }
  started=true;
  const emit=event=>process.stdout.write(JSON.stringify(event)+'\n');
  control(packet,emit,abort.signal,authInteraction(emit,abort.signal,answers)).then(result=>emit({type:'result',result})).catch(()=>{emit({type:'error',message:'Pi 未完成模型操作，请核对网络、授权与模型设置。'});process.exitCode=1;}).finally(()=>{finished=true;abort.abort();lines.close();process.stdin.destroy();});
 });
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)await main();
