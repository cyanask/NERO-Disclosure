import type {RefObject} from 'react';
import {Button,Empty,Select,Space,Table} from 'antd';
import type {DisclosureEvent} from '../types';
import {display} from '../api';
import {eventStageNames as names} from '../eventDetailView';
import PiRunAudit from './PiRunAudit';
const taskStates:Record<string,string>={needs_information:'判断已保存，待补事实',pending:'待领取',claimed:'已领取',submitted:'待核验',adopted:'已载入',expired:'领取已超时',stale:'输入已变化',cancelled:'已取消',failed:'执行失败'};
const auditNames:Record<string,string>={human_confirmation:'人工确认',agent_task_evaluate:'检查候选结果',create:'登记事项',edit:'修改事实',inputs_changed:'输入或任务状态变化',agent_task_request:'创建任务',agent_task_open:'领取任务',agent_task_submit:'提交候选',agent_task_adopt:'载入候选',agent_task_finish:'结束任务',advance:'记录节点通过',law_bindings:'绑定法源',source_search:'登记检索结果',artifact_upload:'登记文件',agent_task_claim:'领取任务',agent_task_heartbeat:'续期任务'};
const auditLabel=(value:string)=>auditNames[value]||(value.endsWith('_blocked')?`${auditNames[value.slice(0,-8)]||value.slice(0,-8)}：已阻断`:value);

export default function EventHistory({event,stage,busy,paused,recorded,canRecord,historyRef,tasksRef,onStage,onPreview,onCancel,onRecordCheck}:{event:DisclosureEvent;stage:string;busy:boolean;paused:boolean;recorded:boolean;canRecord:boolean;historyRef:RefObject<HTMLDetailsElement>;tasksRef:RefObject<HTMLDetailsElement>;onStage:(stage:string)=>void;onPreview:(id:string)=>void;onCancel:(id:string)=>void;onRecordCheck:()=>void}){
 const tasks=event.agent_tasks||[];
 return (<details className="event-history" ref={historyRef}><summary>办理历史</summary>
   <details><summary>人工确认与失效记录（{event.approval_records?.length||0}）</summary>{event.approval_records?.length?event.approval_records.map(r=><p key={r.id}>{names[r.node]||r.node} · {r.reviewer} · {({current:'记录为有效',invalidated:'已失效',superseded:'已替代',rejected:'已退回'} as Record<string,string>)[r.state]||r.state} · {r.reason}{r.invalidation_reason&&`；${r.invalidation_reason}`}</p>):<p>尚无人工确认记录。</p>}</details>
   <details ref={tasksRef} tabIndex={-1}><summary>任务明细（{tasks.length}）</summary>  <Table size="small" rowKey="id" dataSource={tasks} scroll={{x:720}} columns={[{title:'节点',dataIndex:'stage',width:110,render:v=>names[v]||v},{title:'状态',dataIndex:'status',width:110,render:v=>taskStates[v]||v},{title:'执行说明',dataIndex:'status_reason'},{title:'操作',width:180,render:(_,task)=><Space wrap>{task.result&&<Button type="link" className="text-link" onClick={()=>onPreview(task.id)}>查看候选</Button>}{['pending','claimed','expired','submitted'].includes(task.status)&&<Button type="text" disabled={busy} onClick={()=>onCancel(task.id)}>取消任务</Button>}</Space>}]} locale={{emptyText:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无节点任务"/>}}/>
</details>
   <details><summary>办理变更（{event.audit.length}）</summary>  <Table size="small" rowKey={(_,i)=>String(i)} dataSource={[...event.audit].reverse()} scroll={{x:740}} columns={[{title:'时间',dataIndex:'at',width:165,render:v=>new Date(v).toLocaleString('zh-CN')},{title:'来源',dataIndex:'actor',width:130},{title:'动作',dataIndex:'action',width:160,render:auditLabel},{title:'版本',dataIndex:'revision',width:65,render:v=>`r${v}`},{title:'说明',dataIndex:'detail',render:value=>typeof value==='object'&&value!==null?<details><summary>查看完整记录</summary><pre className="snapshot">{display(value)}</pre></details>:display(value)||'—'}]}/>
</details>
   <details><summary>技术执行明细</summary><PiRunAudit board={event.layer} companyCode={event.stock_code} eventId={event.id}/></details>
   <details className="event-management"><summary>管理操作</summary><p>切换查看环节或手动记录检查结果。记录检查不会代替人工确认。</p><div className="run-toolbar"><Select aria-label="选择检查节点" value={stage} disabled={busy} onChange={onStage} options={Object.entries(names).filter(([value])=>event.output_mode!=='text'||!['template','word'].includes(value)).map(([value,label])=>({value,label}))}/><Button disabled={paused||!canRecord||recorded} onClick={onRecordCheck}>{recorded?'已记录自动检查':'记录自动检查'}</Button></div></details>
  </details>);
}
