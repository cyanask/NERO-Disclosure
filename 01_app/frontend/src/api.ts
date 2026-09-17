let csrf = '';
const uncertainRequests = new Map<string, string>();
export function setCsrf(value?:string) { csrf = value || ''; if(!csrf)uncertainRequests.clear(); }
export const humanText=(value:string,fallback='公开条款（标题待核对）')=>/^[A-Za-z0-9_.:-]+$/.test(value)?fallback:value;
export class ApiError extends Error { constructor(public status:number,message:string) {super(message);} }
export async function api<T>(path:string, method='GET', body?:unknown,options:{signal?:AbortSignal}={}):Promise<T> {
  // A lost response must not create another event/draft when the same action is retried.
  let retryKey:string|undefined;
  if(body && typeof body==='object' && 'request_id' in body){
    const {request_id,...payload}=body as Record<string,unknown>;
    retryKey=`${method}:${path}:${JSON.stringify(payload)}`;
    const id=uncertainRequests.get(retryKey)||String(request_id);
    uncertainRequests.set(retryKey,id);
    body={...payload,request_id:id};
  }
  let response:Response;
  try {response=await fetch(`/api${path}`, {method,signal:options.signal,credentials:'same-origin',headers:{...(body !== undefined ? {'Content-Type':'application/json'} : {}),...(method !== 'GET' && csrf ? {'X-CSRF-Token':csrf} : {})},body:body === undefined ? undefined : JSON.stringify(body)});}
  catch {if(options.signal?.aborted)throw options.signal.reason;throw new Error('连接中断，结果尚未确认。请重试同一操作；系统将复用请求编号，避免重复创建。');}
  if (!response.ok) {let detail='请求未完成，请重试';try {const result=await response.json();detail=typeof result.detail==='string'?result.detail:result.detail?.gate?result.detail.message+'：'+[...new Set(result.detail.gate.issues.map((i:{detail:string})=>i.detail))].join('；'):result.detail?.message||JSON.stringify(result.detail);}catch{/* HTTP status remains available */}throw new ApiError(response.status,detail);}
  if(response.status===204){if(retryKey)uncertainRequests.delete(retryKey);return undefined as T;}
  const result=await response.json();
  if(retryKey)uncertainRequests.delete(retryKey);
  return result;
}
export const requestId=()=>crypto.randomUUID();
export const display=(value:unknown):string=>typeof value==='string'?value:JSON.stringify(value,null,2)??'';
// Presentation only: preserve the stored candidate while displaying escaped paragraph breaks.
export const prose=(value?:string)=>(value||'').replace(/\\n/g,'\n');
