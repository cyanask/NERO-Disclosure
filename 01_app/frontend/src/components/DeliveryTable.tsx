import {Button,Empty,Table,Tag} from 'antd';
import type {DisclosureEvent} from '../types';
import type {DocumentVersion} from '../chat';

export type SessionDocument=DocumentVersion&{available:boolean;session_id:string;session_title:string;session_archived:boolean};
export type DocumentListing={items:SessionDocument[];warnings:string[]};
type Delivery={id:string;filename:string;version?:number;sourceTitle:string;sessionId?:string;eventId?:string;archived?:boolean;status:string;available:boolean;download?:string};

export function deliveryRows(events:DisclosureEvent[],documents:SessionDocument[]):Delivery[]{
 const current:Delivery[]=documents.map(d=>({id:`session:${d.session_id}:${d.document_id}`,filename:d.filename,version:d.version,
  sourceTitle:d.session_title,sessionId:d.session_id,archived:d.session_archived,available:d.available,download:d.download,
  status:!d.available?'文件不可用':d.pending.length?`待补 ${d.pending.length} 项`:d.review_status==='accepted'?'已确认 · 未发布':d.review_status==='needs_revision'?'需修改':'待审阅'}));
 const legacy:Delivery[]=events.flatMap(event=>(event.artifacts||[]).map(a=>({id:`event:${event.id}:${a.id}`,filename:a.filename,
  sourceTitle:event.title,eventId:event.id,available:true,download:`/api/events/${event.id}/artifacts/${a.id}/file`,
  status:a.verification.status==='PASS'?'登记检查通过':'登记检查未通过'})));
 return [...current,...legacy];
}

export default function DeliveryTable({rows,busy,onSession,onEvent}:{rows:Delivery[];busy:boolean;onSession:(id:string)=>void;onEvent:(id:string)=>void}){
 return <Table rowKey="id" dataSource={rows} loading={busy} scroll={{x:760}} columns={[
  {title:'文件名称',render:(_,d)=><span>{d.filename} {d.version!==undefined&&<Tag>v{d.version}</Tag>}</span>},
  {title:'所属会话／事项',render:(_,d)=>d.archived?<span>{d.sourceTitle} <Tag>会话已归档</Tag></span>:<Button type="link" className="text-link" onClick={()=>d.sessionId?onSession(d.sessionId):onEvent(d.eventId!)}>{d.sourceTitle}</Button>},
  {title:'状态',width:170,render:(_,d)=><span className="status-text">{d.status}</span>},
  {title:'操作',width:135,render:(_,d)=><Button href={d.available?d.download:undefined} disabled={!d.available||!d.download}>下载 Word</Button>},
 ]} locale={{emptyText:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无已生成的 Word 文件"/>}}/>;
}
