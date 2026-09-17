/** Bound the entire operation (including body reads) and discard late completion. */
export function withDeadline<T>(operation:(signal:AbortSignal)=>Promise<T>,milliseconds:number,parent?:AbortSignal):Promise<T>{
 const controller=new AbortController();
 let timer:ReturnType<typeof setTimeout>;
 let cancel:()=>void;
 const interrupted=new Promise<never>((_,reject)=>{
  cancel=()=>{const reason=parent?.reason||new DOMException('操作已取消','AbortError');controller.abort(reason);reject(reason);};
  if(parent?.aborted){cancel();return;}
  parent?.addEventListener('abort',cancel,{once:true});
  timer=setTimeout(()=>{const reason=new Error('连接超时，请重试');controller.abort(reason);reject(reason);},Math.max(1,milliseconds));
 });
 const work=Promise.resolve().then(()=>{controller.signal.throwIfAborted();return operation(controller.signal);});
 return Promise.race([work,interrupted]).finally(()=>{clearTimeout(timer);parent?.removeEventListener('abort',cancel);});
}

export function pause(milliseconds:number,signal:AbortSignal):Promise<void>{
 return new Promise((resolve,reject)=>{
  if(signal.aborted){reject(signal.reason);return;}
  const cancel=()=>{clearTimeout(timer);reject(signal.reason);};
  const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},milliseconds);
  signal.addEventListener('abort',cancel,{once:true});
 });
}
