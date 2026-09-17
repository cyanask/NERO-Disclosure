import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Modal,Space,Tag} from 'antd';
import {api} from '../api';
import type {DocumentVersion} from '../chat';
import MessageMarkdown from './MessageMarkdown';

type Item=DocumentVersion&{available:boolean;history:DocumentVersion[]};
type Listing={revision:number;items:Item[]};
type Preview={document:DocumentVersion;text:string;notice:string};

/** Preview and download only; revisions are requested in the conversation. */
export default function DocumentPanel({sid,revision}:{sid:string;revision:number}){
 const [data,setData]=useState<Listing>({revision:0,items:[]});
 const [legacy,setLegacy]=useState<{id:string;filename:string;download:string}[]>([]);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [preview,setPreview]=useState<Preview>();
 const scope=useRef(sid);scope.current=sid;
 useEffect(()=>{let current=true;setError('');
  if(!sid){setData({revision:0,items:[]});return;}
  api<Listing>(`/chat/sessions/${sid}/documents`).then(value=>current&&setData(value)).catch(e=>current&&setError(e.message));
  return()=>{current=false;};
 },[sid,revision]);
 useEffect(()=>{setData({revision:0,items:[]});setPreview(undefined);},[sid]);
 useEffect(()=>{let current=true;setLegacy([]);if(sid)api<{items:{id:string;filename:string;download:string}[]}>(`/chat/sessions/${sid}/exports`).then(value=>current&&setLegacy(value.items)).catch(()=>{});return()=>{current=false;};},[sid]);
 const show=async(row:DocumentVersion)=>{
  const target=sid;setBusy(true);setError('');
  try{const value=await api<Preview>(`/chat/sessions/${sid}/documents/${row.document_id}/versions/${row.version}/preview`);if(scope.current===target)setPreview(value);}
  catch(e){if(scope.current===target)setError((e as Error).message);}finally{setBusy(false);}
 };
 if(!sid)return null;
 return <section className="document-panel" aria-label="会话文档">
  <div className="document-panel-heading"><div><h3>文档</h3><p>可预览、下载；需要修改时，直接在对话框说明。</p></div></div>
  {error&&<Alert type="error" message={error} closable onClose={()=>setError('')}/>}
  {notice&&<Alert type="info" message={notice} closable onClose={()=>setNotice('')}/>}
  {data.items.map(item=><article className="document-card" key={item.document_id}>
   <div className="document-card-title"><strong>{item.title}</strong><Tag>v{item.version}</Tag><Tag color={item.review_status==='accepted'?'green':'default'}>{item.review_status==='accepted'?(item.format==='text'?'正文已确认':'已确认 · 未发布'):item.review_status==='needs_revision'?'需修改':'待审阅'}</Tag></div>
   <p>{item.kind==='announcement'?'公告':'咨询回复'} · {item.template_name||'沿用当前稿件版式'}</p>
   {item.warnings?.map((warning,i)=><Alert key={i} type="warning" message={warning}/>)}
   {!!item.pending.length&&<details open><summary>待补事项（{item.pending.length}）</summary><ul>{item.pending.map((p,i)=><li key={i}>{p}</li>)}</ul></details>}
   {!item.available&&<Alert type="error" message="该版本文件缺失或内容已变化，请核对执行记录。"/>}
   {item.format==='text'&&item.text&&<details open><summary>当前公告正文</summary><MessageMarkdown text={item.text}/></details>}
   <Space wrap className="document-actions">
    <Button disabled={!item.available||busy} onClick={()=>void show(item)}>文字预览</Button>
    <Button href={item.available?item.download:undefined} disabled={!item.available||!item.download} onClick={()=>setNotice('已请求浏览器下载；保存完成或策略拦截请查看浏览器下载记录。')}>下载 Word</Button>
   </Space>
   {item.history.length>1&&<details><summary>历史版本</summary>{item.history.slice(1).map(v=><p key={v.version}>v{v.version} · {new Date(v.created*1000).toLocaleString()} · {v.download?<a href={v.download}>下载</a>:'文本版本'} <Button type="link" onClick={()=>void show(v)}>文字预览</Button></p>)}</details>}
  </article>)}
  {!!legacy.length&&<details><summary>历史咨询导出</summary>{legacy.map(row=><p key={row.id}><a href={row.download}>{row.filename}</a></p>)}</details>}
  <Modal open={!!preview} title={preview?`${preview.document.title} v${preview.document.version}`:''} footer={null} onCancel={()=>setPreview(undefined)} width={860}>
   <p>{preview?.notice}</p><pre className="document-text-preview">{preview?.text}</pre>
  </Modal>
 </section>;
}
