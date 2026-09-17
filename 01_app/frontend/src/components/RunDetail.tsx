import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Descriptions,Input,Modal,Space} from 'antd';
import {api,display,requestId,prose} from '../api';
import type {DisclosureEvent,Gate,Meta} from '../types';
import {stages} from '../types';
import Evidence from './Evidence';
import DisclosureConfirmation,{DraftingSupplements} from './DisclosureConfirmation';
import EventHistory from './EventHistory';
import EventResultPreview,{CandidateContent} from './EventResultPreview';
import {currentEventStage,eventDetailState,eventStageNames as names} from '../eventDetailView';
import './EventDetail.css';

export default function RunDetail({event,meta,onChanged,onLibrary}:{event:DisclosureEvent;meta:Meta;onChanged:(e:DisclosureEvent)=>void;onLibrary:()=>void}){
 const [stageOverride,setStageOverride]=useState<string>();
 const stage=stageOverride||currentEventStage(event);
 const historyRef=useRef<HTMLDetailsElement>(null),tasksRef=useRef<HTMLDetailsElement>(null),checksRef=useRef<HTMLDetailsElement>(null);
 const [resultOpen,setResultOpen]=useState(false);
 useEffect(()=>{setStageOverride(undefined);setResultOpen(false);},[event.id,event.stage]);
 const [checked,setChecked]=useState<{revision:number;stage:string;gate:Gate}>();
 const [checkError,setCheckError]=useState('');
 const [checking,setChecking]=useState(false);
 const [retry,setRetry]=useState(0);
 const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);
 const [preview,setPreview]=useState<string>();
 const [binding,setBinding]=useState('');
 useEffect(()=>{setBinding(Object.entries(event.law_bindings||{}).map(([a,b])=>`${a} = ${b}`).join('\n'));},[event.id,event.law_bindings]);
 useEffect(()=>{
  let active=true;setChecking(true);setCheckError('');setChecked(undefined);
  api<Gate>(`/events/${event.id}/verify?stage=${stage}`).then(gate=>{if(active)setChecked({revision:event.revision,stage,gate});}).catch(e=>{if(active)setCheckError(e.message);}).finally(()=>{if(active)setChecking(false);});
  return()=>{active=false;};
 },[event.id,event.revision,stage,retry]);
 const gate=checked?.revision===event.revision&&checked.stage===stage?checked.gate:undefined;
 const write=async(suffix:string,body:object)=>{
  setBusy(true);setError('');
  try{onChanged(await api<DisclosureEvent>(`/events/${event.id}${suffix}`,'POST',{expected_revision:event.revision,request_id:requestId(),...body}));return true;}
  catch(e){setError((e as Error).message);try{onChanged(await api<DisclosureEvent>(`/events/${event.id}`));}catch{setError(`${(e as Error).message}；未能刷新记录，请稍后重新打开事项。`);}return false;}
  finally{setBusy(false);}
 };
 const tasks=event.agent_tasks||[];
 const candidate=tasks.find(t=>t.id===preview);
 const fields=meta.event_types.find(t=>t.id===event.kind)?.fields||[];
 const groups=new Map<string,{detail:string;sources:string[]}>();
 gate?.issues.forEach(issue=>{const key=`${issue.code}:${issue.detail}`;const group=groups.get(key)||{detail:issue.detail,sources:[]};if(issue.source_id&&!group.sources.includes(issue.source_id))group.sources.push(issue.source_id);groups.set(key,group);});
 const recorded=gate?.status==='PASS'&&event.verified_stages?.[stage]?.input_fingerprint===gate.input_fingerprint;
 const paused=busy||checking||!gate;
 const view=eventDetailState(event,stage,gate);
 const resultLabel=stage==='assessment'?'判断内容':stage==='plan'?'规划内容':stage==='template'?'模板适配内容':stage==='draft'?'公告正文':'Word 文件';
 const summary=!view.result&&view.candidate?view.candidate.result?.summary||'已有候选内容，尚未载入当前事项。':stage==='assessment'?event.assessment?.summary:stage==='plan'&&event.plan?`已形成 ${event.plan.documents?.length||event.plan.items.length} 项文件或内容规划。`:stage==='template'&&event.template?`已记录模板适配及 ${event.template.adaptations.length} 项调整。`:stage==='draft'&&event.draft?'已形成公告正文，可展开查看每份文件的完整内容。':stage==='word'&&view.result?'已登记当前 Word 文件，可打开核对内容与排版。':undefined;
 const revealTasks=()=>{if(historyRef.current)historyRef.current.open=true;if(tasksRef.current){tasksRef.current.open=true;tasksRef.current.scrollIntoView({block:'nearest'});tasksRef.current.focus();}};
 return <section className="resource-page run-detail event-detail-view">
  <div className="event-detail-heading"><h1>{event.title}</h1><span>{names[stage]} · r{event.revision}</span><span className="event-overall-stage">{stages[event.stage]||event.stage}</span></div>
  {error&&!candidate&&<Alert type="error" message={error} closable onClose={()=>setError('')}/>}
  <section className={`event-current-state ${gate?.status==='BLOCKED'?'needs-attention':''}`} aria-label="当前情况与下一步" aria-busy={checking}>
   <div className="event-state-copy"><h2>{checkError?'暂时无法核对当前情况':checking?'正在核对当前情况':view.title}</h2><p>{checkError?'请重试核验；当前不提供确认操作。':checking?'核对完成后显示本阶段可执行的操作。':view.description}</p></div>
   <div className="event-main-actions">
    {!checking&&!checkError&&view.active.length>0&&<Button type="primary" onClick={revealTasks}>查看任务进展</Button>}
    {!checking&&!checkError&&view.canReview&&<DisclosureConfirmation event={event} stage={stage} gate={gate} busy={busy} write={write} compact presentation="detail"/>}
    {!checking&&!checkError&&!view.active.length&&view.confirmed&&<Button type="primary" onClick={()=>setResultOpen(true)}>查看已确认结果</Button>}
    {!checking&&!checkError&&!view.active.length&&!view.result&&view.candidate&&<Button type="primary" onClick={()=>setPreview(view.candidate!.id)}>查看候选结果</Button>}
    {!checking&&!checkError&&!view.active.length&&gate&&gate.status!=='PASS'&&!view.confirmationSupported&&(!view.candidate||!!view.result)&&<Button type="primary" onClick={()=>{if(checksRef.current){checksRef.current.open=true;checksRef.current.focus();}}}>查看待处理问题</Button>}
    <Button type="text" loading={checking} disabled={busy} onClick={()=>setRetry(n=>n+1)}>{checkError?'重试核验':'重新核验'}</Button>
   </div>
   <details className="event-check-details" ref={checksRef} tabIndex={-1}><summary>查看核验详情{groups.size?`（${groups.size} 项待处理）`:''}</summary>
    {checkError&&<p>{checkError}</p>}
    {!view.confirmationSupported&&<p>此环节不记录人工确认。请在对话操作台继续修订，再返回核验。</p>}
    {!!groups.size&&<ul className="gate-issues">{[...groups.entries()].map(([key,group])=><li key={key}>{group.detail}{!!group.sources.length&&<details><summary>涉及 {group.sources.length} 条依据</summary><p className="source-ids">{group.sources.join('、')}</p></details>}</li>)}</ul>}
    {!!gate?.semantic_review?.length&&<ul>{gate.semantic_review.map((item,i)=><li key={i}>{item.detail}</li>)}</ul>}
    {!!gate?.warnings?.length&&<ul>{gate.warnings.map((item,i)=><li key={i}>{item.detail}</li>)}</ul>}
    {view.lawProblem&&<Button type="link" className="text-link" onClick={onLibrary}>核对法律库与适用版本 →</Button>}
    {gate&&<p className="boundary-note">{gate.boundary}</p>}
   </details>
   <p className="event-confirmation-boundary">产品内确认不等同于法定审批或公开披露。</p>
  </section>
  {event.escalation&&<Alert type="warning" message={event.escalation.reason} action={<Button disabled={busy} onClick={()=>write('/reopen',{stage:event.escalation!.node,reason:'本机使用者已检查问题，恢复当前节点'})}>人工恢复当前节点</Button>}/>}
  <section className="event-existing-result" aria-label="已有结果"><div><h2>已有结果</h2><span>{!view.result?(view.candidate?'候选内容，尚未载入':'尚无本阶段结果'):view.outdated?'历史结果，需重新核验':view.confirmed?'当前版本已确认':gate?.status==='PASS'?'本阶段检查已通过':gate?'尚未通过当前检查':'尚未核验'}</span></div>
   <p className="event-result-summary">{prose(summary)||'本阶段尚未形成结果。已有任务和历史结果可在下方办理历史中查看。'}</p>
   {(view.result||view.candidate)&&<Button type="link" className="text-link" onClick={()=>view.result?setResultOpen(true):setPreview(view.candidate!.id)}>查看{view.result?resultLabel:'候选内容'} →</Button>}
  </section>
  <details className="facts-details"><summary>事实与依据</summary><DraftingSupplements event={event} stage={stage} busy={busy} write={write}/>{event.summary&&<p className="preserve">{event.summary}</p>}<Descriptions bordered column={1} size="small">{Object.entries(event.facts).map(([key,value])=>{const field=fields.find(f=>f.key===key);const option=field?.options?.find(o=>(typeof o==='string'?o:o.value)===value);return <Descriptions.Item key={key} label={field?.label||key}>{typeof option==='object'?option.label:typeof value==='boolean'?(value?'是':'否'):display(value)}</Descriptions.Item>;})}</Descriptions><details className="event-binding-editor"><summary>修改法源绑定</summary><p className="muted binding-note">替代法源须先在法律库登记替代关系。每行填写“原法源编号 = 适用版本编号”；保存后旧判断和任务失效。</p><Input.TextArea aria-label="当前事项法源绑定" value={binding} onChange={e=>setBinding(e.target.value)} rows={3}/><Button className="binding-save" disabled={busy||!binding.trim()} onClick={()=>{const pairs=binding.split('\n').filter(x=>x.trim()).map(x=>x.split('=').map(s=>s.trim()));if(pairs.some(x=>x.length!==2||!x[0]||!x[1])){setError('请按每行“原编号 = 适用版本编号”填写');return;}void write('/law-bindings',{bindings:Object.fromEntries(pairs)});}}>保存法源绑定</Button></details>{!!event.assessment?.citations?.length&&<Evidence items={event.assessment.citations}/>}{event.source_search&&<details><summary>外部检索记录</summary><p>{event.source_search.message}</p></details>}</details>

  <EventHistory event={event} stage={stage} busy={busy} paused={paused} recorded={recorded} canRecord={gate?.status==='PASS'} historyRef={historyRef} tasksRef={tasksRef} onStage={setStageOverride} onPreview={id=>{setError('');setPreview(id);}} onCancel={id=>{void write(`/agent-tasks/${id}/finish`,{status:'cancelled',reason:'本机管理台取消任务'});}} onRecordCheck={()=>{void write('/advance',{stage});}}/>
  <EventResultPreview event={event} stage={stage} open={resultOpen} onClose={()=>setResultOpen(false)} outdated={view.outdated} confirmed={!!view.confirmed} resultLabel={resultLabel}/>
  <Modal className="event-result-modal" title={`${names[candidate?.stage||'']||'节点任务'}候选`} open={!!candidate} width={860} onCancel={()=>{if(!busy)setPreview(undefined);}} footer={<Space><Button disabled={busy} onClick={()=>setPreview(undefined)}>关闭</Button><Button type="primary" loading={busy} disabled={candidate?.status!=='submitted'} onClick={async()=>{if(candidate&&await write(`/agent-tasks/${candidate.id}/adopt`,{}))setPreview(undefined);}}>核验并载入</Button></Space>}>
   <p className="muted">载入前重新核验法源、适用期间和上游依赖；候选不能越过检查。</p>{error&&<Alert type="error" message={error}/>} {candidate&&<CandidateContent result={candidate.result} sources={candidate.candidate_sources}/>}
  </Modal>
 </section>;
}
