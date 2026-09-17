import contract from '../../config/model-contract.json';

export const modelDefaults=contract.defaults;
export const credentialSecretFields=contract.secretCredentialFields;
export const modelThinkingLevels=contract.thinkingLevels;
export const modelApiOptions=contract.apis.map(item=>({value:item.id,label:item.label}));

export interface ModelProfile {
 key:string;label:string;provider:string;id:string;api:string;baseUrl:string;
 auth_type:'environment'|'api_key'|'oauth'|'local'|'google_oauth';api_key_env:string;
 enabled:boolean;visible:boolean;contextWindow:number;maxTokens:number;reasoning_effort:string;thinking_levels:string[];thinking_level_map?:Record<string,string|null>;source:string;compat?:Record<string,unknown>;input?:string[];
 configured?:boolean;credential_configured?:boolean;reason?:string;
}
export interface ModelCheck {status:string;model:string;reasoning_effort:string;at:number;seconds:number;message?:string}
export interface ModelSettingsSnapshot {revision:number;models:ModelProfile[];routes:Record<string,string>;pi_version:string;vault:{available:boolean;label:string};checks:Record<string,ModelCheck>;running?:boolean;provider_catalogs?:Record<string,{listed:number}>;gemini_broker?:{status:string;message:string;model_ids:string[]}|null}
export interface CatalogModel {id:string;label:string;api:string;baseUrl:string;thinking_levels:string[];thinking_level_map?:Record<string,string|null>;contextWindow:number;maxTokens:number;input:string[];reasoning:boolean;compat?:Record<string,unknown>;catalog?:boolean}
export interface ProviderSync {status:string;provider?:string;reason?:string;source?:string;endpoint?:string;listed?:number;added?:number;updated?:number;skipped?:number;models?:string[]}
export interface ModelCatalog {version:string;generated_at:number;source:string;providers:{id:string;name:string;baseUrl:string;auth_types:string[];dynamic:boolean;credential_fields?:string[];models:CatalogModel[]}[]}
export interface LoginJob {id:string;model_key:string;provider?:string;status:string;user_code?:string;url?:string;message?:string;expires_at:number;prompt_id?:string;prompt?:{type:'text'|'secret'|'manual_code'|'select';message:string;placeholder?:string;options?:{id:string;label:string}[]}}

export function newModelProfile(key:string):ModelProfile {
 return {key,label:'',provider:'openai',id:'',api:'openai-responses',baseUrl:'https://api.openai.com/v1',
  auth_type:'api_key',api_key_env:'',enabled:true,visible:true,contextWindow:modelDefaults.contextWindow,
  maxTokens:modelDefaults.maxTokens,reasoning_effort:'off',thinking_levels:['off'],source:'custom'};
}

export function profileFromCatalog(base:ModelProfile,providerId:string,model?:CatalogModel,baseUrl=''):ModelProfile {
 const thinking=model?.thinking_levels||['off'];
 const broker=providerId==='nero-opencodex-loopback';
 return {...base,provider:providerId,id:model?.id||'',label:model?.label||'',
  api:model?.api||'openai-completions',baseUrl:model?.baseUrl||baseUrl,
  auth_type:broker?'google_oauth':providerId==='openai-codex'?'oauth':'api_key',
  contextWindow:model?.contextWindow||modelDefaults.contextWindow,maxTokens:model?.maxTokens||modelDefaults.maxTokens,
  thinking_levels:thinking,thinking_level_map:model?.thinking_level_map,compat:model?.compat,input:model?.input,
  reasoning_effort:broker?'high':thinking.includes('medium')?'medium':thinking[0]||'off',source:model?'pi_builtin':'custom'};
}
export const modelFields=(row:ModelProfile):ModelProfile=>{const {configured,credential_configured,reason,...fields}=row;return fields;};
export const routeLabels:Record<string,string>={default:'所有节点默认',chat:'普通聊天',assessment:'披露判断',plan:'文件与内容规划',template:'模板适配',draft:'正文制作',word:'Word 制作'};
export const profileLabel=(row:{label:string;reasoning_effort?:string})=>`${row.label}${row.reasoning_effort&&row.reasoning_effort!=='off'?` · ${row.reasoning_effort}`:''}`;
export function authorizationRows(rows:ModelProfile[]):ModelProfile[]{
 return rows.filter((row,index)=>row.auth_type!=='google_oauth'&&(!['oauth','api_key'].includes(row.auth_type)||rows.findIndex(other=>other.provider===row.provider&&other.auth_type===row.auth_type)===index));
}

export const providerFamily=(id:string)=>({openai:'gpt','openai-codex':'gpt',google:'gemini','nero-opencodex-loopback':'gemini','google-vertex':'gemini',moonshotai:'kimi','moonshotai-cn':'kimi','kimi-coding':'kimi','minimax-cn':'minimax','zai-coding-cn':'zai'}[id]||id);
export interface ProviderGroup {id:string;name:string;providerIds:string[];models:ModelProfile[];catalogProviders:ModelCatalog['providers'];registered:boolean;authorization:string;authorized:boolean}
export function groupProviders(models:ModelProfile[],catalog?:ModelCatalog):ProviderGroup[]{
 const ids=Array.from(new Set([...models.map(m=>m.provider),...(catalog?.providers.map(p=>p.id)||[])]));
 const families=Array.from(new Set(ids.map(providerFamily)));
 const order=['gpt','gemini','deepseek','kimi'];
 families.sort((a,b)=>(order.includes(a)?order.indexOf(a):99)-(order.includes(b)?order.indexOf(b):99));
 return families.map(id=>{
  const providerIds=ids.filter(p=>providerFamily(p)===id),rows=models.filter(m=>providerIds.includes(m.provider));
  const catalogProviders=catalog?.providers.filter(p=>providerIds.includes(p.id))||[];
  const modes=Array.from(new Set([...rows.map(m=>m.auth_type),...catalogProviders.flatMap(p=>p.id==='nero-opencodex-loopback'?['google_oauth']:p.id==='openai-codex'?['oauth']:p.auth_types.includes('api_key')?['api_key']:[])]));
  const labels=modes.map(mode=>{const present=rows.some(m=>m.auth_type===mode&&m.credential_configured);return mode==='google_oauth'?`Google / agy 授权${present?'已连接':'未连接'}`:mode==='oauth'?`${id==='gpt'?'ChatGPT':'账号'} 授权${present?'已配置':'未连接'}`:mode==='api_key'?`API Key ${present?'已配置':'未配置'}`:mode==='local'?'本机服务':`环境变量${present?'已配置':'未配置'}`;});
  const name=({gpt:'OpenAI / GPT',gemini:'Google / Gemini',deepseek:'DeepSeek',kimi:'Moonshot / Kimi',minimax:'MiniMax',zai:'智谱 / Z.ai',custom:'自定义兼容接口'} as Record<string,string>)[id]||catalogProviders[0]?.name||id;
  return {id,name,providerIds,models:rows,catalogProviders,registered:rows.length>0,authorization:labels.join(' · ')||'未配置',authorized:rows.some(m=>m.credential_configured)};
 });
}
