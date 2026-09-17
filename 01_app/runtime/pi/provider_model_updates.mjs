// Exact upstream metadata absent from the installed Pi release catalog.
// Verified 2026-09-17 against Pi's published model configuration and OpenCode's endpoint table:
// https://pi.dev/models/opencode-go/deepseek-v4-1-flash
// https://opencode.ai/docs/go/#endpoints
// No inferred aliases: when the installed Pi adds this ID, its own definition takes precedence.
const updates=[{
 id:'deepseek-v4.1-flash',name:'DeepSeek V4.1 Flash',provider:'opencode-go',api:'openai-completions',
 baseUrl:'https://opencode.ai/zen/go/v1',reasoning:true,input:['text','image'],
 thinkingLevelMap:{minimal:null,low:null,medium:null,high:'high',max:'max'},
 contextWindow:1000000,maxTokens:384000,
 cost:{input:0.15,output:0.6,cacheRead:0.003,cacheWrite:0},
 compat:{supportsStore:false,supportsDeveloperRole:false,maxTokensField:'max_tokens',
  requiresReasoningContentOnAssistantMessages:true,thinkingFormat:'deepseek'},
}];

export function withModelUpdates(provider){
 const additions=updates.filter(model=>model.provider===provider.id);
 if(!additions.length)return provider;
 return {...provider,getModels:()=>{
  const native=provider.getModels(),ids=new Set(native.map(model=>model.id));
  return [...native,...additions.filter(model=>!ids.has(model.id)).map(model=>structuredClone(model))];
 }};
}
