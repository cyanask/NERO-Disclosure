import {Button,Empty,Progress,Select,Space,Table,Tag} from 'antd';
import type {Law,Laws,Model,Batch} from './types';
import {stamp,liveBatch as live} from './display';
const lawTitle=(value:string)=>value.replace(/\s+第[一二三四五六七八九十百千万零〇两]+条.*$/,'');
const validityNames:Record<string,string>={current:'本轮未发现失效',repealed:'已废止',superseded:'已被替代',not_yet_effective:'尚未生效',uncertain:'效力待核实'};
export default function LawPanel({laws,models,modelKey,batch,busy,onModel,onRefresh,onStart,onCancel,onOpenSession}:{laws?:Laws;models:Model[];modelKey:string;batch?:Batch;busy:boolean;onModel:(key:string)=>void;onRefresh:()=>void;onStart:(ids?:string[])=>void;onCancel:()=>void;onOpenSession:(sid:string)=>void}){
 return <>
  <div className="gov-toolbar"><div><h2>法规有效性</h2><p>逐部核验当前法规库，检查废止、替代与生效安排；原文一致不等于当前有效。</p></div>
   <Space wrap><Button loading={busy} onClick={onRefresh}>手动刷新清单</Button>
    <Select aria-label="法规核验模型" value={modelKey||undefined} placeholder="选择核验模型" options={models.map(m=>({value:m.key,label:m.label}))} onChange={onModel} disabled={busy||live(batch)} style={{minWidth:210}}/>
    <Button type="primary" disabled={busy||live(batch)||!laws?.records.length||!modelKey} onClick={()=>onStart()}>全库核验{laws?`（${laws.records.length} 项）`:''}</Button></Space></div>
  {batch&&<div className="gov-batch" role="status"><Space wrap><strong>{live(batch)?'全库核验进行中':batch.status==='completed'?'本次检查已结束':batch.status==='partial'?'检查结束，部分结果待核实':batch.status==='cancelled'?'已停止后续核验':'检查未全部完成'}</strong>
   <span>{batch.completed} / {batch.total} 项 · 本批范围 {batch.coverage_articles} 条登记内容</span>
   {live(batch)&&<Button danger disabled={busy} onClick={onCancel}>停止全库核验</Button>}
   <Button type="link" onClick={()=>onOpenSession(batch.session_id)}>查看核验过程</Button></Space>
   <Progress percent={batch.total?Math.floor(batch.completed/batch.total*100):0} status={live(batch)?'active':'normal'} showInfo={false}/>
   <p>{batch.items.find(r=>r.run_id===batch.active_run_id)?.title||batch.error||'检查结束不代表所有法规有效，请核对下列效力结论及依据。'}</p></div>}
  {!laws?<Empty description="尚未读取法规清单。点击“手动刷新清单”后，可发起全库核验。"/>:<>
   <p className="gov-summary">共 {laws.records.length} 项法源／{laws.records.reduce((n,r)=>n+r.article_count,0)} 条登记内容 · 失效或被替代 {laws.records.filter(r=>['repealed','superseded'].includes(r.validity||'')).length} 项 · 效力待核实 {laws.records.filter(r=>!r.validity||r.validity==='uncertain').length} 项 <span>清单读取于 {stamp(laws.generated_at)}</span></p>
   <Table<Law> rowKey="instrument_id" dataSource={laws.records} pagination={false} scroll={{x:920}}
    expandable={{expandedRowRender:r=><div className="gov-law-evidence"><p>{r.last_result||'尚未进行有效性核验'}</p>{r.validity_evidence&&<><p>{r.validity_evidence.quote}</p><a href={r.validity_evidence.url} target="_blank" rel="noreferrer">打开效力核验依据</a></>}</div>}}
    columns={[{title:'法规文件',dataIndex:'title',width:320,render:v=><span className="gov-law-name">{lawTitle(v)}</span>},{title:'条款',dataIndex:'article_count',width:60},
    {title:'效力结论',width:130,render:(_,r)=><Tag color={['repealed','superseded'].includes(r.validity||'')?'red':r.validity==='current'?'green':'orange'}>{validityNames[r.validity||'uncertain']}</Tag>},
    {title:'最近核验',width:150,render:(_,r)=>stamp(r.last_checked_at)},
    {title:'操作',width:180,render:(_,r)=><Space wrap><Button type="link" disabled={busy||live(batch)||!modelKey} onClick={()=>onStart([r.instrument_id])}>核验此法规</Button>{r.url&&<a href={r.url} target="_blank" rel="noreferrer">登记原文</a>}</Space>}]} /></>}
 </>;
}
