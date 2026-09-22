import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Modal} from 'antd';
import {api} from '../api';
import type {PiRun} from '../chat';
import {deliveredWords} from '../conversationPresentation';
import type {ListedDocument} from '../conversationPresentation';

type Preview={text:string;notice?:string};
/** Delivery actions belong to their answer. No standalone document area. */
export default function DocumentPanel({run,items=[]}:{run:PiRun;items?:ListedDocument[]}){
 const [preview,setPreview]=useState<(Preview&{title:string})>();
 const [busy,setBusy]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const scope=useRef(run.session_id);scope.current=run.session_id;
 const request=useRef(0);
 useEffect(()=>()=>{request.current++;},[run.session_id]);
 const show=async(url:string,title:string)=>{
  const seq=++request.current,target=run.session_id;setBusy(url);setError('');
  try{const result=await api<Preview>(url);if(scope.current===target&&seq===request.current)setPreview({...result,title});}
  catch(e){if(scope.current===target&&seq===request.current)setError((e as Error).message);}
  finally{if(scope.current===target&&seq===request.current)setBusy('');}
 };
 const words=deliveredWords(run,items);
 const artifact=run.artifact_id&&!words.length?`/api/events/${run.event_id}/artifacts/${run.artifact_id}`:'';
 if(!words.length&&!artifact)return null;
 return <div className="answer-deliveries" aria-label="本条回复的Word交付物">
  {words.map(word=><div className="answer-delivery" key={`${word.document_id}:${word.version}`}>
   <p className="delivery-label">{word.title} · v{word.version} · {word.review_status==='accepted'?'已确认 · 未发布':word.review_status==='needs_revision'?'需修改':'待审阅'}</p>
   {word.pending?.length>0&&<p className="delivery-warning">待补：{word.pending.join('；')}</p>}
   {word.warnings?.map((warning,i)=><p className="delivery-warning" key={i}>{warning}</p>)}
   {word.available===false&&<p className="delivery-warning" role="alert">该版本文件缺失或内容已变化，请核对执行记录。</p>}
   <div className="delivery-actions"><Button size="small" disabled={word.available===false||!!busy} onClick={()=>void show(`/chat/sessions/${run.session_id}/documents/${word.document_id}/versions/${word.version}/preview`,`${word.title} · v${word.version}`)}>预览正文</Button>
    <Button size="small" href={word.available===false?undefined:word.download} disabled={word.available===false||!word.download} onClick={()=>setNotice('已请求下载；保存结果请查看浏览器下载记录。')}>下载 Word</Button></div>
  </div>)}
  {artifact&&<div className="answer-delivery"><p className="delivery-label">本轮 Word 工作稿 · 待审阅</p><div className="delivery-actions"><Button size="small" disabled={!!busy} onClick={()=>void show(artifact.replace(/^\/api/, '')+'/preview','本轮 Word 工作稿')}>预览正文</Button><Button size="small" href={artifact+'/file'}>下载 Word</Button></div></div>}
  {error&&<Alert type="error" message={error} closable onClose={()=>setError('')}/>}
  {notice&&<p className="delivery-notice" role="status">{notice}</p>}
  <Modal open={!!preview} title={preview?.title} footer={null} onCancel={()=>{request.current++;setBusy('');setPreview(undefined);}} width={860}>
   {preview?.notice&&<p>{preview.notice}</p>}<pre className="document-text-preview">{preview?.text}</pre>
  </Modal>
 </div>;
}
