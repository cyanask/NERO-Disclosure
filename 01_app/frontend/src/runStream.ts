import {api} from './api';
import type {PiRun,Receipt} from './chat';
import {live} from './chat';

export type RunStreamHandlers={
 onReceipt:(row:Receipt)=>void;
 onState:(run:PiRun)=>void;
 onDisconnected:(disconnected:boolean)=>void;
 current:()=>boolean;
};

/** One live subscription. Every asynchronous branch must still belong to this session. */
export function openRunStream(runId:string,handlers:RunStreamHandlers){
 let stream:EventSource|undefined,timer:ReturnType<typeof setTimeout>|undefined;
 let cursor=0,closed=false;
 const valid=()=>!closed&&handlers.current();
 const close=()=>{closed=true;stream?.close();clearTimeout(timer);};
 const append=(row:Receipt)=>{
  if(!valid())return;
  cursor=Math.max(cursor,row.seq);handlers.onReceipt(row);
 };
 const state=(next:PiRun)=>{
  if(!valid())return;
  handlers.onState(next);
  if(!live(next))close();
 };
 const recover=()=>{
  stream?.close();stream=undefined;clearTimeout(timer);
  if(!valid())return;
  handlers.onDisconnected(true);
  timer=setTimeout(async()=>{
   if(!valid())return;
   try{
    let result:{run:PiRun;events:Receipt[]};
    do{
     result=await api<{run:PiRun;events:Receipt[]}>(`/chat/runs/${runId}?after=${cursor}`);
     if(!valid())return;
     result.events.forEach(append);
    }while(result.events.length===1000&&valid());
    if(!valid())return;
    handlers.onDisconnected(false);state(result.run);
    if(valid())connect();
   }catch{if(valid())connect();}
  },2000);
 };
 const connect=()=>{
  if(!valid())return;
  const source=new EventSource(`/api/chat/runs/${runId}/stream?after=${cursor}`);stream=source;
  source.addEventListener('receipt',raw=>{
   if(!valid()||source!==stream)return;
   try{append(JSON.parse((raw as MessageEvent).data));}catch{recover();}
  });
  source.addEventListener('state',raw=>{
   if(!valid()||source!==stream)return;
   try{const next=JSON.parse((raw as MessageEvent).data);handlers.onDisconnected(false);state(next);}catch{recover();}
  });
  source.onerror=()=>{if(source===stream)recover();};
 };
 connect();
 return close;
}
