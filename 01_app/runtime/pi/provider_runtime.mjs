// Keep Pi's provider contracts in the trusted Node runtime, never in browser credentials.
import {createModels, InMemoryCredentialStore} from '@earendil-works/pi-ai';
import {builtinProviders} from '@earendil-works/pi-ai/providers/all';
import {withModelUpdates} from './provider_model_updates.mjs';
import {readFileSync,existsSync} from 'node:fs';
import contract from '../../config/model-contract.json' with {type:'json'};

export const isolatedAuth={env:async()=>undefined,fileExists:async()=>false};
export const PI_VERSION=JSON.parse(readFileSync(new URL('./node_modules/@earendil-works/pi-ai/package.json',import.meta.url),'utf8')).version;
const RUNTIME_VERSION=JSON.parse(readFileSync(new URL('./package.json',import.meta.url),'utf8')).version;
export const credentialFields=id=>[...(contract.credentialFields[id]||[])];
export const runtimeProviders=()=>builtinProviders().map(withModelUpdates);
export const providerById=id=>runtimeProviders().find(provider=>provider.id===id);
export const endpoint=(url,env={})=>Object.entries(env).reduce((value,[key,replacement])=>value.replaceAll(`{${key}}`,replacement),url||'');

// pi-ai 0.85.1 implements the wire protocols, but Pi's OpenCode session attribution
// lives in coding-agent/core/provider-attribution.ts, outside the SDKs we embed.
// Keep this host responsibility at the shared request boundary for every API and
// call purpose. Do not fork the native transports or store a provider-wide ID.
export function providerRequestOptions(model,options){
 let openCode=model.provider==='opencode'||model.provider==='opencode-go';
 try{openCode ||= new URL(model.baseUrl).hostname==='opencode.ai';}catch{}
 if(!openCode)return options;
 if(typeof options.sessionId!=='string'||!options.sessionId.trim())throw new Error('OpenCode requires a conversation session ID');
 const headers={...options.headers};
 // The owning conversation is authoritative, including after a tool or phase
 // transition. Remove case variants so HTTP header normalization cannot combine IDs.
 for(const name of Object.keys(headers))if(['x-opencode-session','x-opencode-client','user-agent'].includes(name.toLowerCase()))delete headers[name];
 return {...options,headers:{...headers,'x-opencode-session':options.sessionId,
  'x-opencode-client':'nero-disclosure','User-Agent':`nero-disclosure/${RUNTIME_VERSION} pi/${PI_VERSION}`}};
}

export async function providerSession(provider,credential){
 const credentials=new InMemoryCredentialStore();
 if(credential)await credentials.modify(provider.id,async()=>credential);
 const env=credential?.env||{};
 const models=createModels({credentials,authContext:{
  env:async name=>env[name],
  fileExists:async path=>path===env.GOOGLE_APPLICATION_CREDENTIALS&&existsSync(path),
 }});
 models.setProvider(provider);
 return {models,credentials};
}

export async function resolveCredential(packet){
 const provider=providerById(packet.provider);
 if(!provider){
  if(packet.credential?.type!=='api_key'||!packet.credential.key)throw new Error('Authorization required');
  return {auth:{apiKey:packet.credential.key},credential:packet.credential,env:{}};
 }
 const {models,credentials}=await providerSession(provider,packet.credential);
 const native=provider.getModels().find(model=>model.id===packet.model?.id&&model.api===packet.model?.api);
 const result=await models.getAuth(native||provider.id);
 if(!result)throw new Error('Authorization required');
 return {auth:result.auth,env:{...packet.credential?.env,...result.env},credential:await credentials.read(provider.id)};
}

export function hydrateModel(model,provider,env={}){
 const native=provider?.getModels().find(item=>item.id===model.id&&item.api===model.api);
 // Custom routes keep their explicitly supplied contract.
 if(!native||endpoint(native.baseUrl,env).replace(/\/$/,'')!==endpoint(model.baseUrl,env).replace(/\/$/,''))return model;
 return {...native,...model,input:native.input,compat:{...native.compat,...model.compat}};
}
