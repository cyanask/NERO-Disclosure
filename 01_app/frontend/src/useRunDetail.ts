import {useCallback,useEffect,useRef,useState} from 'react';
import {api} from './api';
import type {PiRun,Receipt} from './chat';
import {live} from './chat';
import type {DisclosureEvent} from './types';
import {restoreContinuation} from './confirmationContinuation';
import type {ResumePending} from './confirmationContinuation';
import {openRunStream} from './runStream';
import {eventRefreshSequence} from './workProgress';

const PAGE_SIZE=25;
type Detail={event:DisclosureEvent|null;runs:PiRun[]};
type Options={sid:string;board:string;companyCode?:string;onReset:()=>void;onEvent:(event:DisclosureEvent)=>void;
 onResume:(pending:ResumePending)=>void;onError:(message:string)=>void};

export function mergeReceipts(old:Receipt[],incoming:Receipt[]):Receipt[]{
 return [...new Map([...old,...incoming].map(row=>[row.seq,row])).values()].sort((a,b)=>a.seq-b.seq);
}

/** Own loading, replay and subscription for one selected session. DOM navigation stays with the view. */
export function useRunDetail(options:Options){
 const {sid,board,companyCode=''}=options;
 const callbacks=useRef(options);callbacks.current=options;
 const generation=useRef(0);
 const [runs,setRuns]=useState<PiRun[]>([]);
 const [receipts,setReceipts]=useState<Record<string,Receipt[]>>({});
 const [audit,setAudit]=useState('');
 const [detailReload,setDetailReload]=useState(0);
 const [loadedSid,setLoadedSid]=useState('');
 const [loading,setLoading]=useState(false);
 const [disconnected,setDisconnected]=useState(false);
 const [hasOlderRuns,setHasOlderRuns]=useState(false);
 const [loadingOlder,setLoadingOlder]=useState(false);
 const current=runs[0],running=runs.find(live);
 const eventReceipt=eventRefreshSequence(current,receipts[current?.id||'']||[]);

 const readReceipts=useCallback(async(rounds:PiRun[],valid:()=>boolean)=>{
  const all:Record<string,Receipt[]>={};
  for(const run of rounds){
   let cursor=0;const rows:Receipt[]=[];
   while(valid()){
    const page=await api<{events:Receipt[]}>(`/chat/runs/${run.id}?after=${cursor}`);
    if(!valid())return;
    rows.push(...page.events);
    if(page.events.length<1000)break;
    cursor=page.events.at(-1)!.seq;
   }
   if(!valid())return;
   all[run.id]=rows;
  }
  if(valid())setReceipts(prev=>{
   const next={...prev};
   for(const [id,rows] of Object.entries(all))next[id]=mergeReceipts(rows,prev[id]||[]);
   return next;
  });
 },[]);

 useEffect(()=>{
  const gen=++generation.current;let active=true;
  const valid=()=>active&&gen===generation.current;
  setRuns([]);setReceipts({});setAudit('');setLoadedSid('');setLoading(!!sid);setDisconnected(false);
  setHasOlderRuns(false);setLoadingOlder(false);callbacks.current.onReset();
  if(sid)void(async()=>{try{
   const detail=await api<Detail>(`/chat/sessions/${sid}?company=${companyCode}&limit=${PAGE_SIZE}&offset=0`);
   if(!valid())return;
   if(detail.event&&detail.event.layer!==board)throw new Error('会话不属于当前板块');
   if(detail.event)callbacks.current.onEvent(detail.event);
   setRuns(detail.runs);setHasOlderRuns(detail.runs.length===PAGE_SIZE);
   const recovered=restoreContinuation(detail.event||undefined,sid,detail.runs);
   if(recovered)callbacks.current.onResume(recovered);
   await readReceipts(detail.runs,valid);
   if(valid())setLoadedSid(sid);
  }catch(e){if(valid())callbacks.current.onError((e as Error).message);}
   finally{if(valid())setLoading(false);}})();
  return()=>{active=false;generation.current++;};
 },[sid,board,companyCode,detailReload,readReceipts]);

 useEffect(()=>{
  if(!running)return;
  const gen=generation.current;
  return openRunStream(running.id,{
   current:()=>gen===generation.current,
   onReceipt:row=>setReceipts(prev=>({...prev,[running.id]:mergeReceipts(prev[running.id]||[],[row])})),
   onState:next=>setRuns(prev=>prev.map(r=>r.id===next.id?next:r)),
   onDisconnected:setDisconnected,
  });
 },[running?.id,sid,board,companyCode,detailReload]);

 useEffect(()=>{
  if(!current||disconnected||current.event_id.startsWith('conversation:'))return;
  const gen=generation.current;let active=true;
  api<DisclosureEvent>(`/events/${current.event_id}${companyCode?`?company=${companyCode}`:''}`).then(event=>{
   if(active&&gen===generation.current)callbacks.current.onEvent(event);
  }).catch(e=>{if(active&&gen===generation.current)callbacks.current.onError(e.message);});
  return()=>{active=false;};
 },[current?.id,current?.event_id,current?.stage,current?.status,eventReceipt,disconnected]);

 const loadOlderRuns=async()=>{
  if(!sid||loadingOlder||!hasOlderRuns)return;
  const gen=generation.current;const valid=()=>gen===generation.current;
  setLoadingOlder(true);
  try{
   const detail=await api<Detail>(`/chat/sessions/${sid}?company=${companyCode}&limit=${PAGE_SIZE}&offset=${runs.length}`);
   if(!valid())return;
   await readReceipts(detail.runs,valid);
   if(!valid())return;
   setRuns(prev=>[...prev,...detail.runs.filter(r=>!prev.some(p=>p.id===r.id))]);
   setHasOlderRuns(detail.runs.length===PAGE_SIZE);
  }catch(e){if(valid())callbacks.current.onError((e as Error).message);}
  finally{if(valid())setLoadingOlder(false);}
 };
 return {runs,setRuns,receipts,setReceipts,audit,setAudit,detailReload,setDetailReload,
  generation,loadedSid,loading,disconnected,hasOlderRuns,loadingOlder,loadOlderRuns};
}
