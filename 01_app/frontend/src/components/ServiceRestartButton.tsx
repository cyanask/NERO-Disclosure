import {useEffect,useRef,useState} from 'react';
import {Button} from 'antd';
import {ApiError,api,setCsrf} from '../api';
import {withDeadline} from '../requestLifetime';
import {recoverService,RestartRejected} from '../serviceRecovery';
import type {ServiceState} from '../serviceRecovery';

export default function ServiceRestartButton({visible,disabled,onRestored,onNotice,onError}:{visible:boolean;disabled:boolean;onRestored:(signal?:AbortSignal)=>Promise<void>;onNotice:(text:string)=>void;onError:(text:string)=>void}){
 const [service,setService]=useState<ServiceState>(),[phase,setPhase]=useState<'idle'|'waiting'|'timeout'>('idle');
 const [unavailable,setUnavailable]=useState('');
 const previous=useRef(''),post=useRef<AbortController>();
 const callbacks=useRef({onRestored,onNotice,onError});callbacks.current={onRestored,onNotice,onError};
 useEffect(()=>()=>post.current?.abort(),[]);
 useEffect(()=>{
  if(phase!=='waiting')return;
  const controller=new AbortController(),signal=controller.signal;
  callbacks.current.onError('');callbacks.current.onNotice('正在重启服务，页面将自动恢复连接……');
  void recoverService(previous.current,signal).then(async result=>{
   signal.throwIfAborted();setCsrf(result.csrf);setService(result.service);
   try{await withDeadline(s=>callbacks.current.onRestored(s),Math.min(10000,result.remainingMs),signal);}
   catch(e){if(signal.aborted)return;callbacks.current.onError('服务已恢复，但版本信息未刷新：'+(e as Error).message);}
   if(signal.aborted)return;
   callbacks.current.onNotice('服务已重启并恢复连接。');setPhase('idle');
  }).catch(e=>{
   if(signal.aborted)return;
   callbacks.current.onNotice('');callbacks.current.onError((e as Error).message);
   setPhase(e instanceof RestartRejected?'idle':'timeout');
  });
  return()=>controller.abort();
 },[phase]);
 useEffect(()=>{
  if(!visible||phase!=='idle')return;
  const controller=new AbortController();let timer:number;
  const refresh=async()=>{
   try{
    const value=await withDeadline(s=>api<ServiceState>('/governance/service/restart','GET',undefined,{signal:s}),3000,controller.signal);
    if(controller.signal.aborted)return;setService(value);setUnavailable('');
    if(value.pending){previous.current=value.instance_id;setPhase('waiting');return;}
   }catch(e){if(controller.signal.aborted)return;setUnavailable(e instanceof ApiError&&e.status===404?'当前服务尚未加载重启功能，请通过项目启动入口重启一次。':'暂时无法读取重启状态。');}
   if(!controller.signal.aborted)timer=window.setTimeout(refresh,5000);
  };
  void refresh();return()=>{controller.abort();window.clearTimeout(timer);};
 },[visible,phase]);
 const restart=async()=>{
  if(!service||phase!=='idle'||post.current)return;
  const controller=new AbortController();post.current=controller;
  previous.current=service.instance_id;setPhase('waiting');
  try{await withDeadline(signal=>api('/governance/service/restart','POST',{instance_id:service.instance_id},{signal}),10000,controller.signal);}
  catch(e){if(!controller.signal.aborted&&e instanceof ApiError){setPhase('idle');callbacks.current.onNotice('');callbacks.current.onError(e.message);}}
  finally{if(post.current===controller)post.current=undefined;}
  // Network uncertainty is handled by observation, never by repeating the POST.
 };
 const reason=unavailable||service?.reason||'重启本机服务并重新加载代码';
 return <Button className="service-restart-button" title={reason} loading={phase==='waiting'} disabled={phase==='idle'&&(disabled||!!unavailable||!service?.can_restart)} onClick={()=>phase==='timeout'?setPhase('waiting'):void restart()}>{phase==='waiting'?'正在重启…':phase==='timeout'?'重试连接':'重启服务'}</Button>;
}
