import type {ReactNode} from 'react';
import {Alert,Button,Empty,Space,Table,Tag} from 'antd';
import type {Health,HealthRun,HealthTask,Finding} from './types';
import {facts,size,stamp} from './display';
const taskNames:Record<string,string>={pending:'等待领取',claimed:'已领取',expired:'领取超时',submitted:'待核验',failed:'门禁阻断',stale:'输入已变化',needs_information:'待补资料',adopted:'已载入',cancelled:'已取消'};
const runTone=(status:string)=>status==='failed'||status==='interrupted'?'red':status==='incomplete'?'orange':status==='blocked'?'purple':status==='waiting_user'?'gold':status==='completed'?'green':status==='running'||status==='cancelling'?'blue':undefined;
const taskTone=(status:string)=>['submitted','claimed'].includes(status)?'orange':status==='expired'||status==='failed'?'red':undefined;
const uptime=(value:number)=>value>=86400?`${Math.floor(value/86400)} 天 ${Math.floor(value%86400/3600)} 小时`:value>=3600?`${Math.floor(value/3600)} 小时 ${Math.floor(value%3600/60)} 分`:`${Math.max(1,Math.floor(value/60))} 分`;
export default function HealthPanel({health,busy,onScan,onStop,findingAction,onOpenSession,onOpenEvent}:{health?:Health;busy:boolean;onScan:()=>void;onStop:(id:string)=>void;findingAction:(finding:Finding)=>ReactNode;onOpenSession:(id:string)=>void;onOpenEvent:(id:string)=>void}){
 const countNames:Record<string,string>={events:'事项',sessions:'会话',runs:'执行',announcements:'公告'};
 return <>
  <div className="gov-toolbar"><div><h2>运行健康与恢复</h2><p>读取服务、Pi 引擎、执行记录、节点任务与数据库状态，并给出可执行的下一步。系统故障可在此恢复；业务核验未通过仍须补资料或修订。</p></div>
   <Space wrap><Button loading={busy} onClick={onScan}>手动检查</Button></Space></div>
  {!health?<Empty description="点击“手动检查”，读取服务、Pi 引擎、执行记录、节点任务与数据库状态。"/>:<>
   <p className="gov-summary">检查于 {stamp(health.scanned_at)} · 用时 {health.elapsed_ms} ms · 服务进程 {health.service.pid} 已运行 {uptime(health.service.uptime_seconds)} <span>{health.service.entry}</span></p>
   {health.findings.map((finding,index)=><Alert key={`${finding.code}-${index}`} showIcon type={finding.level==='attention'?'warning':'info'} message={finding.message} description={finding.detail} action={findingAction(finding)}/>)}
   {!health.findings.length&&<Alert type="success" showIcon message="未发现需要处理的运行问题。"/>}
   <h3 className="gov-section">服务与 Pi 引擎</h3>
   {facts([['Pi 引擎',`${health.engine.name} ${health.engine.version||''}${health.engine.installed?' · 已安装':' · 未就绪'}`],
    ['执行环境',`Node ${health.engine.node||'未找到'} · worker ${health.engine.worker_present?'就绪':'缺失'} · 核心依赖 ${health.engine.core_present?'就绪':'缺失'}`],
    ['运行中轮次',health.engine.active_rounds],['模型','共 '+health.engine.models.total+' 个 · 已配置 '+health.engine.models.configured+' 个 · 已启用 '+health.engine.models.enabled+' 个'],
    ['默认路由',health.engine.default_route],['模型配置',health.engine.configuration_path],['模型设置版本','r'+health.engine.settings_revision],
    ['数据目录',health.service.directory],['项目目录',health.service.project_root],['Python',health.service.python],['磁盘剩余',size(health.storage.disk.free)+' / '+size(health.storage.disk.total)]])}
   {health.engine.error&&<Alert type="warning" message={health.engine.error}/>}
   <h3 className="gov-section">最近执行与恢复</h3>
   <p className="muted">当前提醒仅统计各会话最新一轮；较早的执行作为历史保留。完整过程与人工处理入口见“执行记录”。</p>
   {!health.runs.rows.length?<p className="muted">本项目还没有执行记录。</p>:<Table<HealthRun> size="small" rowKey="run_id" dataSource={health.runs.rows} pagination={{pageSize:8}} scroll={{x:1120}}
    columns={[{title:'状态',width:150,render:(_,r)=><><Tag color={runTone(r.status)}>{r.status_name}</Tag>{r.is_current===false&&!r.live&&<small>历史</small>}</>},{title:'会话',width:220,render:(_,r)=><Button type="link" className="text-link" onClick={()=>onOpenSession(r.session_id)}>{r.session_title}</Button>},
     {title:'阶段／模型',width:200,render:(_,r)=><span className="gov-fact">{r.stage_name||'—'}{r.model&&` · ${r.model}`}</span>},
     {title:'更新时间',width:165,render:(_,r)=>stamp(r.updated_iso)},
     {title:'说明与下一步',render:(_,r)=><span className="gov-fact">{r.blockers?.length?`${r.gate_scope==='current_event'?'当前事项':'本轮'}阻断项：${r.blockers.join('；')}。${r.next_step}`:[r.provider_error||r.reason,r.next_step].filter(Boolean).join(' ')}</span>},
     {title:'操作',width:150,render:(_,r)=><Space wrap><Button size="small" disabled={busy||!r.live} onClick={()=>onStop(r.run_id)}>停止执行</Button><Button size="small" onClick={()=>onOpenSession(r.session_id)}>打开会话</Button></Space>}]}/>}
   <h3 className="gov-section">待核对的占位任务</h3>
   <p className="muted">正常执行中的节点 {health.tasks.active_count??0} 个。</p>
   {!health.tasks.hanging.length?<p className="muted">没有脱离执行轮次的占位任务。</p>:<Table<HealthTask> size="small" rowKey="task_id" dataSource={health.tasks.hanging} pagination={false} scroll={{x:1120}}
    columns={[{title:'事项',width:220,render:(_,t)=>t.event_title},{title:'节点',dataIndex:'stage_name',width:110},
     {title:'状态',width:110,render:(_,t)=><Tag color={taskTone(t.status)}>{taskNames[t.status]||t.status}</Tag>},
     {title:'门禁结论',width:140,render:(_,t)=>t.gate_status||t.outcome||'—'},{title:'停留时长',width:110,render:(_,t)=>t.age_seconds===undefined?'—':uptime(t.age_seconds)},
     {title:'说明',dataIndex:'status_reason',render:v=><span className="gov-fact">{v}</span>},
     {title:'操作',width:160,render:(_,t)=><Button size="small" disabled={busy} onClick={()=>onOpenEvent(t.event_id)}>核对并处理此事项</Button>}]}/>}
   {!!health.tasks.escalated.length&&<><h3 className="gov-section">已转人工处理</h3>
    <Table size="small" rowKey="event_id" dataSource={health.tasks.escalated} pagination={false} columns={[{title:'事项',dataIndex:'event_title'},{title:'节点',dataIndex:'node',width:110},{title:'原因',dataIndex:'reason'},{title:'操作',width:170,render:(_,r)=><Button size="small" onClick={()=>onOpenEvent(r.event_id)}>核对并处理此事项</Button>}]}/></>}
   <h3 className="gov-section">数据可读性</h3>
   <Table size="small" rowKey="path" dataSource={health.storage.databases} pagination={false} scroll={{x:1000}}
    columns={[{title:'数据库',dataIndex:'path',render:v=><span className="gov-path">{v}</span>},{title:'大小',width:120,render:(_,r)=>size(r.bytes+r.wal_bytes)},
     {title:'读取',width:100,render:(_,r)=><Tag color={r.readable?'green':'red'}>{r.readable?'正常':'失败'}</Tag>},
     {title:'完整性',width:110,render:(_,r)=><Tag color={r.quick_check==='ok'?'green':'orange'}>{r.quick_check||'未检查'}</Tag>},
     {title:'记录数',width:200,render:(_,r)=>Object.entries(r.counts).map(([name,value])=>`${countNames[name]||name} ${value}`).join(' · ')||'—'},
     {title:'说明',render:(_,r)=>r.error||(r.missing_tables.length?`缺少表：${r.missing_tables.join('、')}`:'表结构完整')}]}/>
   <p className="muted">{health.boundary}</p></>}
 </>;
}
