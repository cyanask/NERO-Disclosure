import {useEffect,useRef,useState} from 'react';
import type {Receipt} from '../chat';

export default function UserQuestion({row,runId,queuedNotice}:{row:Receipt;runId:string;queuedNotice?:string}){
 const [expanded,setExpanded]=useState(false),[overflow,setOverflow]=useState(false);
 const content=useRef<HTMLSpanElement>(null);
 useEffect(()=>{const node=content.current;if(!node||expanded)return;
  const measure=()=>setOverflow(node.scrollHeight>node.clientHeight+1);measure();
  const observer=typeof ResizeObserver!=='undefined'?new ResizeObserver(measure):undefined;observer?.observe(node);
  return()=>observer?.disconnect();
 },[row.body.text,expanded]);
 return <div className="chat-message user" data-message-id={`${runId}:${row.seq}`}>
  <button type="button" className={`question-bubble${expanded?' expanded':''}`} aria-label={expanded?'收起提问':'展开提问'} aria-expanded={expanded}
   onClick={()=>{if(expanded||overflow)setExpanded(v=>!v);}}>
   <span className="question-text" ref={content}>{String(row.body.text)}</span>
   {(overflow||expanded)&&<span className="question-toggle">{expanded?'收起':'展开原文'}</span>}
  </button>
  {Array.isArray(row.body.attachments)&&row.body.attachments.length>0&&<div className="message-attachments" aria-label="本轮补充资料">{row.body.attachments.map((a:{filename:string;id:string})=><span key={a.id}>{a.filename}</span>)}</div>}
  {queuedNotice&&<small role="status">{queuedNotice}</small>}
 </div>;
}
