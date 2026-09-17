// V1: public provider projection; no credentials, filesystem state, or network.
const assert=require('node:assert/strict');
const path=require('node:path');
const {groupProviders,authorizationRows,newModelProfile,profileFromCatalog}=require(path.join(process.argv[2],'modelSettings.js'));
const models=[
 {key:'chatgpt-profile',provider:'openai-codex',auth_type:'oauth',credential_configured:true,enabled:true},
 {key:'api-profile',provider:'openai',auth_type:'api_key',credential_configured:false,enabled:false},
 {key:'deepseek-profile',provider:'deepseek',auth_type:'api_key',credential_configured:true,enabled:true},
];
const catalog={providers:[
 {id:'openai-codex',name:'OpenAI Codex',auth_types:['oauth'],models:[]},
 {id:'openai',name:'OpenAI',auth_types:['api_key'],models:[]},
 {id:'google',name:'Google',auth_types:['api_key','oauth'],models:[]},
 {id:'deepseek',name:'DeepSeek',auth_types:['api_key'],models:[]},
 {id:'anthropic',name:'Anthropic',auth_types:['api_key'],models:[]},
]};
const before=JSON.stringify({models,catalog});const groups=groupProviders(models,catalog);
assert.deepEqual(groups.map(g=>g.id),['gpt','gemini','deepseek','anthropic']);
assert.equal(groups[0].name,'OpenAI / GPT');assert.equal(groups[0].authorization,'ChatGPT 授权已配置 · API Key 未配置');
assert.deepEqual(groups[0].providerIds,['openai-codex','openai']);
assert.deepEqual(groups[0].models.map(m=>m.key),['chatgpt-profile','api-profile']);
assert.equal(groups.filter(g=>!g.registered).length,2);assert.equal(groups.find(g=>g.id==='deepseek').authorization,'API Key 已配置');
assert.equal(groups.find(g=>g.id==='gemini').authorization,'API Key 未配置');
assert.equal(JSON.stringify({models,catalog}),before);
assert.deepEqual(groupProviders(models).map(g=>g.id),['gpt','deepseek']);
assert.equal(groupProviders([]).length,0);
const googleModels=[{key:'gemini-38',provider:'nero-opencodex-loopback',auth_type:'google_oauth',credential_configured:true,enabled:true}];
const googleCatalog={providers:[...catalog.providers,{id:'nero-opencodex-loopback',auth_types:['google_oauth'],models:[]}]};
const google=groupProviders(googleModels,googleCatalog).find(g=>g.id==='gemini');
assert.deepEqual(google.providerIds,['nero-opencodex-loopback','google']);
assert.equal(google.authorization,'Google / agy 授权已连接 · API Key 未配置');
assert.equal(google.authorized,true);
const wideCatalog={providers:[...catalog.providers,{id:'opencode-go',name:'OpenCode Zen Go',auth_types:['api_key'],models:[]},{id:'amazon-bedrock',name:'Amazon Bedrock',auth_types:['api_key'],models:[]}]};
const wide=groupProviders(models,wideCatalog);
assert.deepEqual(wide.filter(g=>['opencode-go','amazon-bedrock'].includes(g.id)).map(g=>g.id),['opencode-go','amazon-bedrock']);
const go=wide.find(g=>g.id==='opencode-go');
assert.equal(go.name,'OpenCode Zen Go');assert.equal(go.authorization,'API Key 未配置');
assert.equal(go.registered,false);assert.equal(go.authorized,false);assert.deepEqual(go.models,[]);
assert.deepEqual(go.catalogProviders.map(p=>p.id),['opencode-go']);
console.log('Provider families, independent auth states, unfiltered catalog entries with no supported models, and immutable source projection passed.');
const goProfiles=Array.from({length:20},(_,index)=>({key:'go-'+index,provider:'opencode-go',auth_type:'api_key'}));
assert.equal(authorizationRows(goProfiles).length,1);
assert.equal(authorizationRows([...goProfiles,{key:'other',provider:'deepseek',auth_type:'api_key'}]).length,2);
const empty=newModelProfile('fixed-key');
assert.equal(empty.maxTokens,16384);assert.equal(empty.contextWindow,128000);
const definition={id:'native-id',label:'Native name',api:'openai-completions',baseUrl:'https://example.invalid/v1',contextWindow:1000000,maxTokens:384000,thinking_levels:['off','high','max'],thinking_level_map:{high:'high',max:'max'},compat:{maxTokensField:'max_tokens'},input:['text','image']};
const initial={...empty,enabled:false,visible:false};
const original=JSON.stringify({initial,definition});
const profile=profileFromCatalog(initial,'opencode-go',definition);
assert.equal(profile.key,'fixed-key');assert.equal(profile.enabled,false);assert.equal(profile.visible,false);
assert.equal(profile.maxTokens,384000);assert.equal(profile.reasoning_effort,'off');assert.equal(profile.auth_type,'api_key');
assert.deepEqual(profile.compat,{maxTokensField:'max_tokens'});
assert.deepEqual(profileFromCatalog(empty,'openai-codex',{...definition,thinking_levels:['low','medium','high']}).auth_type,'oauth');
assert.equal(profileFromCatalog(empty,'nero-opencodex-loopback',{...definition,thinking_levels:['low','high']}).reasoning_effort,'high');
const changed=profileFromCatalog(profile,'another-provider',undefined,'https://other.invalid/v1');
assert.equal(changed.id,'');assert.equal(changed.maxTokens,16384);assert.equal(changed.baseUrl,'https://other.invalid/v1');
assert.equal(changed.compat,undefined);assert.equal(JSON.stringify({initial,definition}),original);
