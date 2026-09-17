import {useEffect,useState} from 'react';
import type {WorkProgress as Progress} from '../workProgress';
import type {PiRun} from '../chat';
import {nodeLabels} from '../chat';
import './WorkProgress.css';

const states={requested:'请求已登记',running:'进行中',done:'已完成',failed:'失败',unknown:'结果未明确'};
export default function WorkProgress({progress,run,runs,open,onOpen,onSelect,onAction,onEvidence,onCurrent,motion:controlledMotion,onMotionChange}:{progress:Progress;run?:PiRun;runs:PiRun[];open:boolean;onOpen:(open:boolean)=>void;onSelect:(id:string)=>void;onAction:()=>void;onEvidence:()=>void;onCurrent:()=>void;motion?:boolean;onMotionChange?:(motion:boolean)=>void}){
 const [localMotion,setLocalMotion]=useState(true),[reduced,setReduced]=useState(false),[all,setAll]=useState(false);
 const motion=controlledMotion??localMotion;
 useEffect(()=>{const m=matchMedia('(prefers-reduced-motion: reduce)');const sync=()=>setReduced(m.matches);sync();m.addEventListener('change',sync);return()=>m.removeEventListener('change',sync);},[]);
 useEffect(()=>setAll(false),[run?.id]);
 if(!run&&!open)return null;
 const rows=all?progress.activities:progress.activities.slice(-6);
 return <section className={`work-progress ${progress.tone}`} aria-label={progress.historical?'历史工作进展':'当前工作进展'} data-motion={progress.animate&&motion&&!reduced?'on':'off'}>
  <div className="work-progress-summary"><span className="work-progress-dot" aria-hidden="true"/><div role="status"><strong>{progress.title}</strong><p>{progress.detail}</p></div>
   {progress.historical?<button onClick={onCurrent}>返回当前会话</button>:progress.action&&<button onClick={onAction}>{progress.actionLabel}</button>}
  </div>
  <details open={open} onToggle={e=>onOpen(e.currentTarget.open)}><summary>工作轨迹<span>{open?'收起':'展开'}</span></summary>
   <div className="work-progress-body">
    {run&&<div className="work-progress-tools"><label>查看范围 <select aria-label="工作进展轮次" value={run.id} onChange={e=>onSelect(e.target.value)}>{runs.map((r,i)=><option key={r.id} value={r.id}>{i===0?'当前轮':'历史轮次'} · {nodeLabels[r.stage]||'需求处理'} · {new Date(r.created*1000).toLocaleString('zh-CN')}</option>)}</select></label><button aria-pressed={!motion||reduced} disabled={reduced} onClick={()=>onMotionChange?onMotionChange(!motion):setLocalMotion(!motion)}>{reduced?'系统已减弱动效':motion?'暂停动效':'开启动效'}</button></div>}
    {progress.activities.length>6&&<button onClick={()=>setAll(v=>!v)}>{all?'只看最近活动':`展开更早活动（共 ${progress.activities.length} 条）`}</button>}
    <ol className="work-activities">{rows.map(a=><li key={a.key} data-activity-state={a.state}><div><strong>{a.label}</strong>{a.detail&&<p>{a.detail}</p>}</div><small>{states[a.state]}</small></li>)}</ol>
    {!rows.length&&<p className="work-progress-empty">{run?'尚无可确认的活动记录。':'直接说明需求即可，不必选择固定路线。'}</p>}
    {run&&<div className="work-progress-footer"><span>只展示已发生的工作，不预设后续步骤。</span><button onClick={onEvidence}>查看本轮依据</button></div>}
   </div>
  </details>
 </section>;
}
