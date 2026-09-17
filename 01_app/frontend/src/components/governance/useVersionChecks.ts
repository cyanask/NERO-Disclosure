import {useEffect,useRef,useState} from 'react';
import {api,requestId} from '../../api';
import {withDeadline} from '../../requestLifetime';
import type {Version,Verify} from './versionTypes';
export const verifying=(value?:Verify)=>!!value&&['running','cancelling'].includes(value.state);

/** Version snapshot and one progress subscription; scanning remains explicit. */
export function useVersionChecks(initial:{version?:Version;verify?:Verify},active:boolean){
 const [version,setVersion]=useState(initial.version),[verify,setVerify]=useState(initial.verify);
 const [watchVerify,setWatchVerify]=useState(false),[verifyError,setVerifyError]=useState(''),[pollKey,setPollKey]=useState(0);
 const lifetime=useRef(new AbortController());
 useEffect(()=>{lifetime.current=new AbortController();return()=>lifetime.current.abort();},[]);
 useEffect(()=>{
  if(!active)return;
  const controller=new AbortController();let timer:number;
  const poll=async()=>{
   try{
    const value=await withDeadline(signal=>api<Verify|null>('/governance/version/verify','GET',undefined,{signal}),5000,controller.signal);
    if(controller.signal.aborted)return;setVerify(value||undefined);setVerifyError('');setWatchVerify(verifying(value||undefined));
    if(verifying(value||undefined))timer=window.setTimeout(poll,2000);
   }catch(e){if(!controller.signal.aborted){setVerifyError((e as Error).message);setWatchVerify(false);}}
  };
  void poll();return()=>{controller.abort();window.clearTimeout(timer);};
 },[active,pollKey]);
 const refreshVerify=async()=>{setVerifyError('');setPollKey(n=>n+1);};
 const scanVersion=async(signal?:AbortSignal)=>{
  const local=lifetime.current.signal;
  const value=await withDeadline(s=>api<Version>('/governance/version/scan','POST',{}, {signal:s}),30000,signal||local);
  local.throwIfAborted();signal?.throwIfAborted();setVersion(value);await refreshVerify();
 };
 const startVerify=async()=>{
  const signal=lifetime.current.signal;
  const value=await withDeadline(s=>api<Verify>('/governance/version/verify','POST',{request_id:requestId()},{signal:s}),10000,signal);
  signal.throwIfAborted();setVerify(value);await refreshVerify();
 };
 const cancelVerify=async()=>{
  if(!verify)return;const signal=lifetime.current.signal;
  const value=await withDeadline(s=>api<Verify>('/governance/version/verify/cancel','POST',{request_id:verify.request_id},{signal:s}),10000,signal);
  signal.throwIfAborted();setVerify(value);await refreshVerify();
 };
 return {version,verify,watchVerify,verifyError,scanVersion,refreshVerify,startVerify,cancelVerify};
}
