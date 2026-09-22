import {useEffect,useState} from 'react';
import {api} from '../api';
import type {PiRun} from '../chat';
import {deliveredTexts} from '../conversationPresentation';
import type {ListedDocument} from '../conversationPresentation';
import MessageMarkdown from './MessageMarkdown';

function RegisteredText({sid,document,answer}:{sid:string;document:ListedDocument;answer:string}){
 const [text,setText]=useState(document.text||''),[error,setError]=useState('');
 useEffect(()=>{let current=true;setText(document.text||'');setError('');
  if(!document.text&&document.available!==false)api<{text:string}>(`/chat/sessions/${sid}/documents/${document.document_id}/versions/${document.version}/preview`)
   .then(value=>{if(current)setText(value.text);}).catch(e=>{if(current)setError(e.message);});
  return()=>{current=false;};
 },[sid,document.document_id,document.version,document.text,document.available]);
 if(document.available===false||error)return <p role="alert" className="delivery-warning">已保存的正文暂时无法读取：{error||'该版本缺失或内容已变化'}</p>;
 if(!text)return <p className="delivery-label">正在读取已保存的公告正文…</p>;
 const duplicate=answer.replace(/\s/g,'').includes(text.replace(/\s/g,''));
 return <div className="chat-message assistant registered-text" aria-label="已保存的公告正文">
  {!duplicate&&<MessageMarkdown text={text}/>}
  <p className="delivery-label">正文 v{document.version} · {document.review_status==='accepted'?'已确认 · 未发布':'待审阅'}</p>
 </div>;
}
export default function RoundTextDelivery({run,items,answer}:{run:PiRun;items:ListedDocument[];answer:string}){
 return <>{deliveredTexts(run,items).map(document=><RegisteredText key={`${document.document_id}:${document.version}`} sid={run.session_id} document={document} answer={answer}/>)}</>;
}
