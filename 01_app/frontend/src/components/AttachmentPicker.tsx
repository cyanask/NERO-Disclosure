import {useRef} from 'react';
import {Button} from 'antd';
import {PaperClipOutlined,CloseOutlined} from '@ant-design/icons';
import {api} from '../api';

export async function uploadAttachments(sid:string,files:File[]):Promise<string[]>{
 const identities:string[]=[];
 for(const file of files){
  const encoded=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error(`无法读取附件：${file.name}`));reader.readAsDataURL(file);});
  const result=await api<{id:string}>(`/chat/sessions/${sid}/attachments`,'POST',{filename:file.name,content_base64:encoded});
  identities.push(result.id);
 }
 return [...new Set(identities)];
}

export default function AttachmentPicker({files,disabled,onChange,onError}:{files:File[];disabled:boolean;onChange:(files:File[])=>void;onError:(message:string)=>void}){
 const input=useRef<HTMLInputElement>(null);
 return <div className="attachment-picker">
  <input ref={input} type="file" accept=".docx,.xlsx" multiple hidden aria-label="选择Word或Excel补充资料" onChange={e=>{
   const incoming=Array.from(e.target.files||[]);e.target.value='';
   if(files.length+incoming.length>8){onError('每轮最多选择8份附件。');return;}
   const invalid=incoming.find(f=>!(/\.(docx|xlsx)$/i.test(f.name))||f.size>20*1024*1024||!f.size);
   if(invalid){onError(`附件“${invalid.name}”须为非空的 .docx/.xlsx，且不超过20MB。`);return;}
   onChange([...files,...incoming]);
  }}/>
  <Button size="small" icon={<PaperClipOutlined/>} disabled={disabled} onClick={()=>input.current?.click()}>添加资料</Button>
  <span className="attachment-hint">Word / Excel · 发送后用于本会话资料核对</span>
  {!!files.length&&<ul className="attachment-files">{files.map((file,index)=><li key={`${file.name}-${index}`}>
   <span title={file.name}>{file.name}</span><Button type="text" size="small" icon={<CloseOutlined/>} disabled={disabled} aria-label={`移除待发送附件：${file.name}`} onClick={()=>onChange(files.filter((_,n)=>n!==index))}/>
  </li>)}</ul>}
 </div>;
}
