import {api} from './api';
import {pause,withDeadline} from './requestLifetime';
export type ServiceState={instance_id:string;supported:boolean;pending:boolean;can_restart:boolean;reason:string;error:string};
export class RestartRejected extends Error{}
type RecoveryIO={state:(signal:AbortSignal)=>Promise<ServiceState>;session:(signal:AbortSignal)=>Promise<{csrf_token:string}>};
const io:RecoveryIO={state:signal=>api('/governance/service/restart','GET',undefined,{signal}),session:signal=>api('/session','GET',undefined,{signal})};

/** Observe only: a lost restart response never causes another POST. */
export async function recoverService(previous:string,signal:AbortSignal,options:{timeoutMs?:number;attemptMs?:number;intervalMs?:number;io?:RecoveryIO}={}){
 const deadline=Date.now()+(options.timeoutMs??60000),requests=options.io||io;
 const request=<T,>(fn:(signal:AbortSignal)=>Promise<T>)=>withDeadline(fn,Math.min(options.attemptMs??3000,deadline-Date.now()),signal);
 while(Date.now()<deadline){
  signal.throwIfAborted();
  try{
   const service=await request(requests.state);signal.throwIfAborted();
   if(service.error)throw new RestartRejected(service.error);
   if(service.instance_id!==previous&&!service.pending){
    const session=await request(requests.session);signal.throwIfAborted();
    return {service,csrf:session.csrf_token,remainingMs:Math.max(1,deadline-Date.now())};
   }
  }catch(e){if(signal.aborted)throw signal.reason;if(e instanceof RestartRejected)throw e;}
  await pause(Math.min(options.intervalMs??1000,Math.max(1,deadline-Date.now())),signal);
 }
 throw new Error('暂未确认服务恢复。可重试连接；若仍无响应，请检查启动终端或重新运行项目启动入口。');
}
