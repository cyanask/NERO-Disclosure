import {useEffect,useState} from 'react';
import {Alert,Button,Empty,Modal,Select,Table} from 'antd';
import {api,display} from '../api';
import type {PiRun,Receipt} from '../chat';
import {live,runStageLabel,nodeLabels,receiptLabels,runLabels} from '../chat';
import {profileLabel} from '../modelSettings';

export function SessionReceipts({sessionId}:{sessionId:string}){
 const [runs,setRuns]=useState<PiRun[]>([]),[selected,setSelected]=useState(''),[error,setError]=useState('');
 useEffect(()=>{let active=true;api<{runs:PiRun[]}>(`/chat/sessions/${sessionId}`).then(value=>{if(active){setRuns(value.runs);setSelected(value.runs[0]?.id||'');}}).catch(e=>active&&setError(e.message));return()=>{active=false;};},[sessionId]);
 return <>{error&&<Alert type="error" message={error}/>}<p className="muted">系统治理中的原执行记录；查阅不会改变本公司会话范围。</p><Select aria-label="选择核验轮次" value={selected||undefined} style={{width:'100%',marginBottom:16}} onChange={setSelected} options={runs.map(r=>({value:r.id,label:`${runStageLabel(r)} · ${new Date(r.created*1000).toLocaleString('zh-CN')}`}))}/>{selected&&<RunReceipts key={selected} runId={selected}/>}</>;
}

export function RunReceipts({runId}:{runId:string}){
 const [run,setRun]=useState<PiRun>();const [rows,setRows]=useState<Receipt[]>([]);const [error,setError]=useState('');const [filter,setFilter]=useState('all');
 useEffect(()=>{let active=true;let timer:ReturnType<typeof setTimeout>;
  const read=async()=>{try{let cursor=0;const all:Receipt[]=[];let current:PiRun;do{const result=await api<{run:PiRun;events:Receipt[]}>(`/chat/runs/${runId}?after=${cursor}`);current=result.run;all.push(...result.events);if(result.events.length<1000)break;cursor=result.events.at(-1)!.seq;}while(active);
   if(!active)return;setRun(current!);setRows(all);setError('');if(live(current!))timer=setTimeout(read,1500);
  }catch(e){if(active)setError((e as Error).message);}};void read();return()=>{active=false;clearTimeout(timer);};
 },[runId]);
 const shown=rows.filter(row=>row.kind!=='text_delta'&&(filter==='all'||(filter==='messages'?['user','assistant','questions'].includes(row.kind):filter==='tools'?/tool|script|artifact|verification|capability/.test(row.kind):/skill|context|model_input/.test(row.kind))));
 return <div className="pi-audit-detail">{error&&<Alert type="error" message={error}/>}{run&&<><p><strong>{runStageLabel(run)} · {runLabels[run.status]}</strong>　{profileLabel(run.model)}（{run.model.id}）</p><p>{run.reason}</p><p className="muted">Skill：{run.skill_status==='loaded'?`${run.skill?.id} · ${run.skill?.version}`:run.skill_status==='not_applicable'?'本轮不适用':'尚未装载'}。工具传输按实际记录；装载与返回记录不代表业务验收。</p></>}
 <Select aria-label="筛选执行记录" value={filter} onChange={setFilter} options={[{value:'all',label:'全部记录'},{value:'messages',label:'对话与问题'},{value:'tools',label:'工具、脚本与文件'},{value:'context',label:'Skill 与上下文'}]}/>
 <ol className="receipt-list">{shown.map(row=><li key={row.seq}><div><span>{receiptLabels[row.kind]||row.kind}</span><time>{new Date(row.at*1000).toLocaleTimeString('zh-CN')}</time></div>
 {['user','assistant'].includes(row.kind)?<p className="preserve">{String(row.body.text||'（本条仅请求工具）')}</p>:<details><summary>{String(row.body.name||row.body.script||row.body.reason||row.body.id||'查看记录')}</summary><pre className="snapshot">{display(row.body)}</pre></details>}</li>)}</ol>
 </div>;
}

export default function PiRunAudit({board,eventId,onSession,companyCode=''}:{board:string;companyCode?:string;eventId?:string;onSession?:(sid:string)=>void}){
 const [runs,setRuns]=useState<PiRun[]>([]),[selected,setSelected]=useState<PiRun>();const [error,setError]=useState(''),[reload,setReload]=useState(0);
 useEffect(()=>{let active=true;api<PiRun[]>(`/chat/runs?board=${board}&company=${companyCode}`).then(rows=>{if(active){setRuns(rows);setError('');}}).catch(e=>active&&setError(e.message));return()=>{active=false;};},[board,companyCode,reload]);
 return <section className="pi-run-audit"><div className="audit-heading"><div><h2>技术执行明细</h2><p className="muted">每轮对话、模型、Skill、工具与文件回执。</p></div><Button onClick={()=>setReload(n=>n+1)}>刷新</Button></div>{error&&<Alert type="error" message={error}/>}
 <Table size="small" rowKey="id" dataSource={runs.filter(r=>!eventId||r.event_id===eventId)} scroll={{x:720}} columns={[{title:'节点',dataIndex:'stage',render:s=>nodeLabels[s]},{title:'模型',render:(_,r)=>profileLabel(r.model)},{title:'状态',dataIndex:'status',render:s=>runLabels[s]||s},{title:'时间',dataIndex:'created',render:t=>new Date(t*1000).toLocaleString('zh-CN')},{title:'记录',render:(_,r)=><Button type="link" onClick={()=>setSelected(r)}>查看全过程</Button>}]} locale={{emptyText:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无 Pi 执行记录"/>}}/>
 <Modal title="执行全过程" open={!!selected} width={940} onCancel={()=>setSelected(undefined)} footer={<>{onSession&&selected&&<Button onClick={()=>{onSession(selected.session_id);setSelected(undefined);}}>打开所属会话</Button>}<Button onClick={()=>setSelected(undefined)}>关闭</Button></>}>{selected&&<RunReceipts key={selected.id} runId={selected.id}/>}</Modal>
 </section>;
}
