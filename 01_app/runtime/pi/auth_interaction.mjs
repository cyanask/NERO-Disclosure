import {randomUUID} from 'node:crypto';

// Only login UI messages cross this boundary. Tokens and provider progress stay
// in the private command result and are never copied to the public job status.
export function authInteraction(emit,signal,answers){
 return {
  signal,
  prompt:prompt=>new Promise((resolve,reject)=>{
   const id=randomUUID(),abort=()=>{cleanup();answers.delete(id);emit({type:'auth_prompt_cancelled',id});reject(new Error('Login prompt cancelled'));};
   const signals=[signal,prompt.signal].filter(Boolean);
   if(signals.some(s=>s.aborted)){reject(new Error('Login cancelled'));return;}
   const cleanup=()=>signals.forEach(s=>s.removeEventListener('abort',abort));
   answers.set(id,{resolve:value=>{cleanup();resolve(value);},reject:error=>{cleanup();reject(error);}});
   signals.forEach(s=>s.addEventListener('abort',abort,{once:true}));
   emit({type:'auth_prompt',id,prompt:{type:prompt.type,message:prompt.message,placeholder:prompt.placeholder,
    ...(prompt.type==='select'?{options:prompt.options}:{} )}});
  }),
  notify:event=>{
   if(event.type==='device_code')emit({type:'device_code',user_code:event.userCode,url:event.verificationUri,expires_in:event.expiresInSeconds});
   if(event.type==='auth_url')emit({type:'auth_url',url:event.url,instructions:event.instructions});
  },
 };
}
