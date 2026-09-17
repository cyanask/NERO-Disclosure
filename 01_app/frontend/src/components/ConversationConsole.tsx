import RoundArticle from './RoundArticle';
import '../conversationInput.css';
import '../attachments.css';
import AttachmentPicker,{uploadAttachments} from './AttachmentPicker';
import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import type {ComponentRef} from 'react';
import {Alert,Button,Input,Select,Spin} from 'antd';
import {ArrowUpOutlined,StopOutlined} from '@ant-design/icons';
import {api,requestId} from '../api';
import type {DisclosureEvent,Meta} from '../types';
import {stages} from '../types';
import type {ChatSession,PiCapabilities,PiRun,Receipt} from '../chat';
import {live,nodeLabels,runLabels} from '../chat';
import {pendingHumanGate} from '../humanGates';
import {profileLabel} from '../modelSettings';
import {observeContinuation} from '../confirmationContinuation';
import type {ResumePending} from '../confirmationContinuation';
import {workProgress} from '../workProgress';
import WorkProgress from './WorkProgress';
import {savedSessionModel,saveSessionModel,forgetSessionModel,resolveSessionModel,modelAvailable} from '../sessionModels';
import ConversationNavigation from './ConversationNavigation';
import {captureReadingPosition,restoreReadingPosition} from '../readingPosition';
import type {ReadingPosition} from '../readingPosition';
import SessionPanel from './SessionPanel';
import DocumentPanel from './DocumentPanel';
import ConversationWelcome from './ConversationWelcome';
import {useRunDetail} from '../useRunDetail';

export default function ConversationConsole({board,meta,onChanged,onAudit,onSettings,onSessionChange,onEventDeleted,initialSession,navigationHost,companyCode='',companyName='',assistantRequest}:{board:string;meta:Meta;events:DisclosureEvent[];onChanged:(e:DisclosureEvent)=>void;onAudit:(id:string)=>void;onSettings:(sid?:string)=>void;onSessionChange?:(sid:string)=>void;initialSession?:string;onEventDeleted?:(id:string)=>void;navigationHost?:HTMLElement|null;companyCode?:string;companyName?:string;assistantRequest?:{text:string;key:number}}){
 const [showHistory,setShowHistory]=useState(false);
 const [deletion,setDeletion]=useState<{session_id:string;title:string;fingerprint:string;runs:number;records:number;files:{path:string}[];backups:{path:string}[];retained:string[]}>();
 const [sessionsOpen,setSessionsOpen]=useState(()=>typeof window!=='undefined'&&window.matchMedia('(min-width:801px)').matches);
 const formAnchor=useRef<HTMLDivElement>(null),followBottom=useRef(true);
 const [caps,setCaps]=useState<PiCapabilities>();const [sessions,setSessions]=useState<ChatSession[]>([]),[sid,setSid]=useState(initialSession||'');
 const [event,setEvent]=useState<DisclosureEvent>();
 const [modelChoices,setModelChoices]=useState<Record<string,string>>({}),[drafts,setDrafts]=useState<Record<string,string>>({}),[search,setSearch]=useState('');
 const text=drafts[sid]||'';
 const [fileDrafts,setFileDrafts]=useState<Record<string,File[]>>({});
 const [uploading,setUploading]=useState(false);
 const files=fileDrafts[sid]||[];
 const setText=(value:string)=>setDrafts(prev=>({...prev,[sid]:value}));
 useEffect(()=>{if(assistantRequest){setSid('');setDrafts(prev=>({...prev,'':assistantRequest.text}));}},[assistantRequest?.key]);
 const sending=useRef(false);
 const [deliveryMode,setDeliveryMode]=useState<'steer'|'follow_up'>('steer');
 const [resumePending,setResumePending]=useState<ResumePending>();
 const [resumeNotice,setResumeNotice]=useState('');
 const [progressOpen,setProgressOpen]=useState(false),[progressRunId,setProgressRunId]=useState(''),[progressMotion,setProgressMotion]=useState(true);
 const navigationTarget=useRef<'reading'|'progress'|'compose'>('reading');
 const consoleRef=useRef<HTMLElement>(null),progressAnchor=useRef<HTMLDivElement>(null),readingPositions=useRef<Record<string,ReadingPosition>>({});
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[archived,setArchived]=useState(false);
 const [showFacts,setShowFacts]=useState(false),[title,setTitle]=useState(''),[summary,setSummary]=useState(''),[facts,setFacts]=useState<Record<string,unknown>>({});
const [rename,setRename]=useState(false),[renamed,setRenamed]=useState('');
 const bottom=useRef<HTMLDivElement>(null),selectionRef=useRef(sid);selectionRef.current=sid;
 const composer=useRef<ComponentRef<typeof Input.TextArea>>(null),auditAnchor=useRef<HTMLElement>(null);
 const {runs,setRuns,receipts,setReceipts,audit,setAudit,detailReload,setDetailReload,
  loadedSid,loading,disconnected,hasOlderRuns,loadingOlder,loadOlderRuns}=useRunDetail({sid,board,companyCode,
  onReset:()=>{setProgressRunId('');setProgressOpen(false);setShowFacts(false);setShowHistory(false);setEvent(undefined);
   followBottom.current=!readingPositions.current[sid];
   const saved=savedSessionModel(board,sid);if(saved)setModelChoices(prev=>prev[sid]===undefined?{...prev,[sid]:saved}:prev);},
  onEvent:next=>{setEvent(next);onChanged(next);},onError:setError,
  onResume:recovered=>setResumePending(previous=>previous?.sid===sid?previous:recovered),
 });
 const current=runs[0];const running=runs.find(live);
 const selectedModel=resolveSessionModel(caps,sid,loadedSid,runs,modelChoices[sid]);
 const rememberModel=(target:string,key:string)=>{setModelChoices(prev=>({...prev,[target]:key}));if(!saveSessionModel(board,target,key))setError('当前浏览器无法保存模型选择。本页内仍独立保留，刷新后将按该会话最近实际使用的模型恢复。');};
 const modelUnavailable=!!caps&&!!selectedModel&&!modelAvailable(caps,selectedModel);
 const modelOptions=caps?.models.filter(m=>m.visible!==false).map(m=>({value:m.key,label:profileLabel(m),disabled:!m.configured}))||[];
 if(selectedModel&&!modelOptions.some(m=>m.value===selectedModel))modelOptions.push({value:selectedModel,label:'本会话原模型已不可用，请重新选择',disabled:true});
 const scopeRuns=runs.filter(r=>r.session_id===sid);
 const selectedRun=(progressRunId?scopeRuns.find(r=>r.id===progressRunId):scopeRuns[0])||scopeRuns[0];
 const historical=!!selectedRun&&selectedRun.id!==current?.id;
 const pending=pendingHumanGate(event),inputWaiting=current?.status==='waiting_user'&&!running;
 const progress=workProgress(selectedRun,receipts[selectedRun?.id||'']||[],{historical,disconnected:!historical&&disconnected,pendingReview:selectedRun?.event_id===event?.id?pending?.label:undefined});
 const titleReceipt=receipts[current?.id||'']?.find(r=>r.kind==='session_named')?.seq;
 const focusInput=()=>{composer.current?.focus();composer.current?.resizableTextArea?.textArea.scrollIntoView({block:'center',behavior:'instant' as ScrollBehavior});};
 const scrollPanel=()=>bottom.current?.closest<HTMLElement>('.workspace-page');
 const saveReading=()=>{const panel=scrollPanel(),messages=bottom.current?.parentElement;if(!panel||!messages||loadedSid!==sid||navigationTarget.current!=='reading')return;const saved=captureReadingPosition(panel,messages);if(saved)readingPositions.current[sid]=saved;};
 const closeProgress=()=>{setProgressOpen(false);setProgressRunId('');};
 const goProgress=(id?:string)=>{saveReading();navigationTarget.current='progress';followBottom.current=false;setProgressRunId(id&&id!==current?.id?id:'');setProgressOpen(true);};
 const goReading=()=>{closeProgress();const panel=scrollPanel(),messages=bottom.current?.parentElement;if(panel&&messages){navigationTarget.current='reading';followBottom.current=false;restoreReadingPosition(panel,messages,readingPositions.current[sid]);messages.focus({preventScroll:true});}};
 const goCompose=()=>{saveReading();closeProgress();navigationTarget.current='compose';followBottom.current=false;requestAnimationFrame(focusInput);};
 const chooseSession=(next:string)=>{setResumeNotice('');saveReading();navigationTarget.current='reading';setSid(next);};
 const session=sessions.find(s=>s.id===sid);
 const update=(next:DisclosureEvent)=>{setEvent(next);onChanged(next);};
 const list=async()=>{const next=await api<ChatSession[]>(`/chat/sessions?board=${board}&company=${companyCode}&archived=${archived}`);setSessions(next);};
 useEffect(()=>{let ok=true;Promise.all([api<PiCapabilities>('/chat/models'),api<ChatSession[]>(`/chat/sessions?board=${board}&company=${companyCode}&archived=${archived}`)]).then(([c,s])=>{if(!ok)return;setCaps(c);setSessions(s);setSid(old=>s.some(x=>x.id===old)?old:'');}).catch(e=>ok&&setError(e.message));return()=>{ok=false;};},[board,companyCode,archived]);
 useEffect(()=>{if(initialSession)setSid(initialSession);},[initialSession]);
 useEffect(()=>{onSessionChange?.(sid);},[sid,onSessionChange]);
 useEffect(()=>{setResumeNotice('');},[sid]);

 useEffect(()=>{if(sid&&loadedSid===sid&&readingPositions.current[sid])goReading();},[sid,loadedSid]);
 useEffect(()=>{
  if(!resumePending||resumePending.sid!==sid)return;
  let ok=true,timer:ReturnType<typeof setTimeout>;const seen:Record<string,Receipt[]>={};
  const poll=async()=>{try{
   const detail=await api<{runs:PiRun[]}>(`/chat/sessions/${sid}`);if(!ok)return;
   const scoped=detail.runs.filter(r=>r.session_id===sid&&r.event_id===resumePending.eventId);
   // Read the parent's late failure receipt and candidate continuation receipts,
   // including pages beyond the first 1,000 journal entries.
   const parent=scoped.find(r=>r.id===resumePending.parent);
   if(!resumePending.runId)await Promise.all(scoped.filter(r=>r.id===resumePending.parent||!parent||r.created>=parent.created).map(async r=>{
    const rows=seen[r.id]||[];let cursor=rows.at(-1)?.seq||0;
    while(ok){const page=await api<{events:Receipt[]}>(`/chat/runs/${r.id}?after=${cursor}`);if(!ok)return;rows.push(...page.events);if(page.events.length<1000)break;cursor=page.events.at(-1)!.seq;}
    seen[r.id]=rows;
   }));
   if(!ok)return;
   setError(previous=>previous.startsWith('确认已保存，读取自动接续状态暂时失败')?'':previous);
   const result=observeContinuation(resumePending,detail.runs,Object.values(seen).flat());
   if(result.action!=='waiting'){setResumePending(undefined);setDetailReload(n=>n+1);if(result.action==='failed')setError(result.reason||'自动接续未启动。');if(result.action==='paused')setResumeNotice(result.reason||'自动接续已暂停。');return;}
  }catch(e){if(ok)setError(`确认已保存，读取自动接续状态暂时失败，正在重试。${(e as Error).message}`);}
  if(ok)timer=setTimeout(poll,2000);
  };timer=setTimeout(poll,1000);return()=>{ok=false;clearTimeout(timer);};
 },[resumePending,sid]);
 useEffect(()=>{if(showFacts)formAnchor.current?.scrollIntoView({block:"start"});},[showFacts]);
 useEffect(()=>{if(audit)auditAnchor.current?.scrollIntoView({block:'center',behavior:'instant' as ScrollBehavior});},[audit]);


 useEffect(()=>{if(!current)return;let ok=true;api<ChatSession[]>(`/chat/sessions?board=${board}&company=${companyCode}&archived=${archived}`).then(rows=>{if(ok)setSessions(rows);}).catch(e=>ok&&setError(e.message));return()=>{ok=false;};},[current?.id,current?.status,titleReceipt,board,companyCode,archived]);
 useEffect(()=>{const panel=scrollPanel();if(!panel)return;const track=()=>{followBottom.current=panel.scrollHeight-panel.scrollTop-panel.clientHeight<100;};const readingIntent=(e:Event)=>{const target=e.target as HTMLElement;if(target.closest?.('.chat-composer,.session-panel'))return;if(e instanceof KeyboardEvent&&!['PageUp','PageDown','Home','End','ArrowUp','ArrowDown'].includes(e.key))return;navigationTarget.current='reading';};panel.addEventListener('scroll',track,{passive:true});for(const name of ['wheel','pointerdown','keydown'])panel.addEventListener(name,readingIntent,{passive:true});return()=>{panel.removeEventListener('scroll',track);for(const name of ['wheel','pointerdown','keydown'])panel.removeEventListener(name,readingIntent);};},[]);
 useEffect(()=>{const panel=scrollPanel();if(panel&&followBottom.current)panel.scrollTo({top:panel.scrollHeight,behavior:'instant' as ScrollBehavior});},[receipts,sid,showHistory,audit,pending?.stage,inputWaiting,deletion]);
 useEffect(()=>{
  if(loading||!current||live(current)||!receipts[current.id]?.length||!followBottom.current)return;
  const panel=scrollPanel(),rounds=bottom.current?.parentElement?.querySelectorAll('.chat-round');
  const answer=rounds?.[rounds.length-1]?.querySelector('.chat-message.assistant,.round-analysis');
  if(panel&&answer){const header=panel.querySelector<HTMLElement>('.chat-heading')?.offsetHeight||0;panel.scrollTo({top:panel.scrollTop+answer.getBoundingClientRect().top-panel.getBoundingClientRect().top-header-16,behavior:'instant' as ScrollBehavior});followBottom.current=false;}
 },[loading,current?.status,receipts]);
 const act=async(fn:()=>Promise<void>)=>{setBusy(true);setError('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 const send=async()=>{
  if(sending.current||!canSend)return;
  sending.current=true;setBusy(true);setError('');
  const requestSid=sid,value=text,requestFiles=files,requestModel=selectedModel;let created:ChatSession|undefined;
  try{
   if(running){
    await api(`/chat/runs/${running.id}/messages`,'POST',{text:value.trim(),mode:deliveryMode,request_id:requestId()});
    setDrafts(prev=>prev[requestSid]===value?{...prev,[requestSid]:''}:prev);return;
   }
   if(!requestSid)created=await api<ChatSession>('/chat/sessions','POST',{board,company_code:companyCode,title:'新会话',request_id:requestId()});
   const targetSid=created?.id||requestSid;
   setUploading(!!requestFiles.length);
   const attachmentIds=await uploadAttachments(targetSid,requestFiles);setUploading(false);
   const run=await api<PiRun>(`/chat/sessions/${targetSid}/runs`,'POST',{text:value.trim()||'请读取本轮附件，对照当前公告的待补项核对资料，说明可补充内容和仍缺事项。',attachment_ids:attachmentIds,model_key:requestModel,company_code:companyCode,expected_revision:requestSid?event?.revision||0:0,request_id:requestId()});
   // A user may already be composing the next message while this request is in flight.
   setDrafts(prev=>prev[requestSid]===value?{...prev,[requestSid]:''}:prev);
   setFileDrafts(prev=>({...prev,[requestSid]:[]}));
   if(selectionRef.current===requestSid){followBottom.current=true;if(!created)setRuns(prev=>[run,...prev.filter(r=>r.id!==run.id)]);setProgressRunId('');}
  }catch(e){setError((e as Error).message);}
  finally{
   if(created){
    const next=created;setSessions(prev=>[next,...prev.filter(s=>s.id!==next.id)]);
    rememberModel(next.id,requestModel);setModelChoices(prev=>{const choices={...prev};delete choices[''];return choices;});
    setDrafts(prev=>({...prev,[next.id]:prev[requestSid]||'',[requestSid]:''}));
    setFileDrafts(prev=>({...prev,[next.id]:prev[requestSid]||[],[requestSid]:[]}));
    // Select only after POST settles so the detail read cannot overwrite the accepted run.
    if(selectionRef.current===requestSid){setArchived(false);setSid(next.id);}
   }
   sending.current=false;setBusy(false);setUploading(false);
  }
 };
 const saveFacts=()=>act(async()=>{if(!event)return;update(await api<DisclosureEvent>(`/events/${event.id}`,'PATCH',{expected_revision:event.revision,title:title.trim(),summary,facts}));setShowFacts(false);});
 const openNew=()=>{setError('');if(!sid&&!archived){focusInput();return;}setArchived(false);chooseSession('');focusInput();};
 const archiveSession=(item:ChatSession,archive:boolean)=>act(async()=>{await api(`/chat/sessions/${item.id}`,'PATCH',{archived:archive});await list();if(sid===item.id)setSid('');});
 const previewDelete=(item:ChatSession)=>act(async()=>{setDeletion(await api(`/chat/sessions/${item.id}/deletion-preview`));followBottom.current=true;});

 const readOnly=archived||!!session?.archived;
 const sessionReady=!sid||loadedSid===sid;
 const awaitingResume=resumePending?.sid===sid;
 const disabled=busy||!!running||!!awaitingResume||readOnly||!sessionReady;
 const canSend=!busy&&!awaitingResume&&!readOnly&&sessionReady&&!loading&&(!!text.trim()||!!files.length)&&modelAvailable(caps,selectedModel)&&(!running||running.status==='running'&&!files.length);
 const viewEvidence=()=>{if(!selectedRun)return;closeProgress();followBottom.current=false;setAudit(selectedRun.id);requestAnimationFrame(()=>auditAnchor.current?.scrollIntoView({block:'center',behavior:'instant' as ScrollBehavior}));};
 const progressAction=()=>{
  closeProgress();
  if(progress.action==='input'){goCompose();return;}
  if(progress.action==='review'){if(event&&selectedRun?.event_id===event.id)onAudit(event.id);else viewEvidence();return;}
  const scope=consoleRef.current;
  const target=progress.action==='documents'?scope?.querySelector('.document-panel'):scope?.querySelector(`[data-run-id="${CSS.escape(selectedRun?.id||'')}"] [aria-label="知识库变更确认"]`);
  target?.scrollIntoView({block:'center',behavior:'instant' as ScrollBehavior});
 };
 const progressPanel=<div ref={progressAnchor} tabIndex={-1} role="dialog" aria-label="工作进展详情" className="header-progress-content" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();closeProgress();navigationHost?.querySelector<HTMLButtonElement>('.header-progress-trigger')?.focus();}}}><WorkProgress progress={progress} run={selectedRun} runs={scopeRuns} open={progressOpen} onOpen={value=>{if(!value)closeProgress();}} motion={progressMotion} onMotionChange={setProgressMotion} onSelect={id=>{setProgressRunId(id===current?.id?'':id);followBottom.current=false;}} onAction={progressAction} onEvidence={viewEvidence} onCurrent={goCompose}/></div>;
 return <section ref={consoleRef} className="conversation-console">
  {navigationHost&&createPortal(<ConversationNavigation progress={progress} canRead={!loading&&loadedSid===sid&&!!runs.length} open={progressOpen} motion={progressMotion} content={progressPanel} onProgress={()=>goProgress()} onClose={closeProgress} onShown={()=>progressAnchor.current?.focus({preventScroll:true})} onRead={goReading} onCompose={goCompose}/>,navigationHost)}
  {!navigationHost&&progressOpen&&progressPanel}
  {event&&loadedSid===sid&&<div className="work-progress-context"><Button onClick={()=>onAudit(event.id)}>{pending?`事项记录与审阅 · 待${pending.label}`:'事项记录与审阅'}</Button><Button onClick={()=>{setShowHistory(v=>!v);followBottom.current=true;}}>查看确认记录</Button><Button disabled={disabled} onClick={()=>{setTitle(event.title);setSummary(event.summary);setFacts({...event.facts});setShowFacts(true);}}>补充或修订事实</Button></div>}
  {error&&<Alert type="error" message={error} closable onClose={()=>setError('')}/>}
  <div className="conversation-layout">
 <SessionPanel sessions={sessions} sid={sid} search={search} onSearch={setSearch} archived={archived} open={sessionsOpen} busy={busy}
  running={id=>!!live(runs.find(r=>r.session_id===id))} onToggle={()=>setSessionsOpen(v=>!v)} onNew={openNew}
  onChoose={id=>{setError('');chooseSession(id);}} onArchive={archiveSession} onDelete={previewDelete} onArchived={setArchived}/>
  <section className="chat-panel" aria-label="事项对话"><div className="chat-heading"><div><h2>{session?.title||'开启一段工作会话'}</h2><span>{event?`${event.company_name} · ${stages[event.stage]||event.stage} · r${event.revision}`:'信披咨询、公告与 Word 制作、知识库查询及维护'}</span></div>{session&&<div><Button type="text" disabled={disabled} onClick={()=>{setRenamed(session.title);setRename(true);}}>重命名</Button></div>}</div>
   {awaitingResume&&<Alert type="info" message="确认已保存，正在等待自动接续" description="可随时暂停，已保存的正文确认会保留。" action={<Button disabled={busy} onClick={()=>act(async()=>{
    const target=resumePending!;await api<PiRun>(`/chat/runs/${target.parent||target.runId}/cancel`,'POST',{});
    if(selectionRef.current===target.sid){setResumePending(undefined);setResumeNotice('已请求暂停自动接续，正在读取实际状态；已保存的正文确认保留。');setDetailReload(n=>n+1);}
   })}>暂停自动接续</Button>}/>}
   {!awaitingResume&&resumeNotice&&<Alert type="info" message={resumeNotice} closable onClose={()=>setResumeNotice('')}/>}
   <div className="chat-messages" tabIndex={-1} aria-live="polite" aria-relevant="additions text">{hasOlderRuns&&<Button loading={loadingOlder} onClick={()=>{followBottom.current=false;void loadOlderRuns();}}>加载更早的对话</Button>}{loading?<div className="chat-empty"><Spin/></div>:!sid||!runs.length?<ConversationWelcome disabled={disabled} onStart={value=>{setText(text.trim()?`${text}\n\n${value}`:value);goCompose();}}/>:[...runs].reverse().map(run=><RoundArticle key={run.id} run={run} companyCode={companyCode} rows={receipts[run.id]||[]} busy={busy}
    hideQuestions={false} onProgress={()=>goProgress(run.id)}
    audit={{open:audit===run.id,anchor:auditAnchor,toggle:()=>setAudit(audit===run.id?'':run.id),close:()=>setAudit('')}}
    onRunChange={next=>setRuns(prev=>prev.map(r=>r.id===next.id?next:r))}/>)}
   {deletion&&<section className="inline-panel" aria-label="删除会话及全部专属记录"><h3>删除“{deletion.title}”</h3><p>将清理 {deletion.runs} 次运行、{deletion.records} 条消息及执行记录、{deletion.files.length} 个专属文件，并清理 {deletion.backups.length} 份后台备份内的会话副本。删除后无法通过归档恢复。</p>{deletion.retained.map((v,i)=><p key={i}>{v}</p>)}<details><summary>具体文件和备份范围</summary>{[...deletion.files,...deletion.backups].map(x=><p key={x.path}>{x.path}</p>)}</details><div className="inline-actions"><Button disabled={busy} onClick={()=>setDeletion(undefined)}>取消</Button><Button danger loading={busy} onClick={()=>act(async()=>{const target=deletion;const removed=await api<{deleted_event_id?:string}>(`/chat/sessions/${target.session_id}`,'DELETE',{fingerprint:target.fingerprint});if(removed.deleted_event_id)onEventDeleted?.(removed.deleted_event_id);setDrafts(prev=>{const next={...prev};delete next[target.session_id];return next;});delete readingPositions.current[target.session_id];forgetSessionModel(board,target.session_id);setModelChoices(prev=>{const next={...prev};delete next[target.session_id];return next;});if(sid===target.session_id){setSid('');setEvent(undefined);setRuns([]);setReceipts({});onSessionChange?.('');}setDeletion(undefined);await list();})}>确认删除会话及全部专属记录</Button></div></section>}
   {showFacts&&event&&<div ref={formAnchor} className="inline-panel" aria-label="补充或修订当前事项"><h3>补充或修订当前事项</h3>
   <Alert type="info" message="保存事实变化后，系统会使受影响的候选和确认失效，保留历史记录。"/>
   <p className="muted">{companyName||event.company_name} · {companyCode||event.stock_code}，公司及板块沿用当前登记。</p>
   <label className="form-label">事项名称</label><Input aria-label="事项名称" value={title} onChange={e=>setTitle(e.target.value)}/>
   <label className="form-label">事实说明</label><Input.TextArea aria-label="事实说明" rows={6} value={summary} onChange={e=>setSummary(e.target.value)} placeholder="说明谁准备做什么、目前进展、已知日期及资料来源。"/>
   <label className="form-label">判断基准日</label><Input aria-label="判断基准日" type="date" value={String(facts.assessment_as_of??'')} onChange={e=>setFacts(prev=>{const next={...prev};if(e.target.value)next.assessment_as_of=e.target.value;else delete next.assessment_as_of;return next;})}/>
   {meta.event_types.find(t=>t.id===event.kind)?.fields.filter(f=>f.key!=='disclosure_profile_id').map(f=><div key={f.key}><label className="form-label">{f.label}{f.required?' · 建议填写':''}</label>{f.type==='boolean'?<Select aria-label={f.label} allowClear style={{width:'100%'}} value={facts[f.key] as boolean|undefined} options={[{value:true,label:'是'},{value:false,label:'否'}]} onChange={v=>setFacts(prev=>({...prev,[f.key]:v??null}))}/>:f.options?<Select aria-label={f.label} allowClear style={{width:'100%'}} value={facts[f.key] as string} options={f.options.map(o=>typeof o==='string'?{value:o,label:o}:o)} onChange={v=>setFacts(prev=>({...prev,[f.key]:v??null}))}/>:<Input aria-label={f.label} type={f.type==='date'?'date':'text'} value={String(facts[f.key]??'')} onChange={e=>setFacts(prev=>({...prev,[f.key]:f.type==='number'&&e.target.value?Number(e.target.value):e.target.value}))}/>}</div>)}
   <div className="inline-actions"><Button disabled={busy} onClick={()=>setShowFacts(false)}>取消</Button><Button type="primary" loading={busy} disabled={!title.trim()||!summary.trim()} onClick={saveFacts}>保存并重新核对版本</Button></div></div>}
   {rename&&<section className="inline-panel" aria-label="重命名会话"><h3>重命名会话</h3><Input aria-label="新的会话名称" value={renamed} onChange={e=>setRenamed(e.target.value)}/><div className="inline-actions"><Button onClick={()=>setRename(false)}>取消</Button><Button disabled={busy||!renamed.trim()} onClick={()=>act(async()=>{await api(`/chat/sessions/${sid}`,'PATCH',{title:renamed.trim()});await list();setRename(false);})}>保存名称</Button></div></section>}
   {showHistory&&event&&<section className="inline-panel" aria-label="事项与确认记录"><h3>{event.title} · r{event.revision}</h3><p>{event.summary}</p><h4>确认记录</h4>{!event.approval_records?.length&&<p>尚无人工确认。</p>}{event.approval_records?.map(r=><p key={r.id}>{nodeLabels[r.node]||r.node} · {r.reviewer} · {r.reason}{r.invalidation_reason&&`；${r.invalidation_reason}`}</p>)}<details><summary>事项变更记录</summary>{event.audit.map((a,i)=><p key={i}>{a.at} · r{a.revision} · {a.actor} · {typeof a.detail==='string'?a.detail:a.action}</p>)}</details><Button onClick={()=>setShowHistory(false)}>收起记录</Button></section>}

   {!!event?.approval_records?.length&&<section className="approval-history" aria-label="人工处理记录">{event.approval_records.map(r=><p key={r.id}>{r.reviewer} · {nodeLabels[r.node]||r.node} · {({current:'当前有效',invalidated:'已失效',superseded:'已替代',rejected:'已退回'} as Record<string,string>)[r.state]||r.state}：{r.reason}{r.invalidation_reason&&`；${r.invalidation_reason}`}</p>)}</section>}
   <DocumentPanel key={sid} sid={sid} revision={current&&!live(current)?current.updated:0}/>
   <div ref={bottom}/></div>
   {historical?<div className="historical-input-notice">正在查看历史轮次；新请求发送到当前会话。<Button onClick={goCompose}>返回当前会话继续提问</Button></div>:<div className="chat-composer"><div className="composer-controls"><Select aria-label="选择本轮模型" placeholder={sid&&!sessionReady?'正在读取本会话模型':'请先配置模型'} value={selectedModel||undefined} disabled={disabled} onChange={key=>rememberModel(sid,key)} options={modelOptions}/><button onClick={()=>onSettings(sid||undefined)}>模型设置</button></div>
    {!caps?.models.some(m=>m.configured)&&<p className="model-missing">尚无已授权模型。请在“模型设置”中完成授权并测试连接。</p>}
    {modelUnavailable&&<p className="model-missing" role="status">本会话所选模型当前不可用，请重新选择可用模型。</p>}
    {sid&&!loading&&!sessionReady&&<p role="status">会话尚未读取成功，可先起草。<Button type="link" disabled={busy} onClick={()=>setDetailReload(n=>n+1)}>重新读取会话</Button></p>}
    <AttachmentPicker files={files} disabled={disabled} onChange={next=>setFileDrafts(prev=>({...prev,[sid]:next}))} onError={setError}/>
    {uploading&&<p role="status">正在上传并解析附件，完成后提交本轮需求…</p>}
    <Input.TextArea ref={composer} aria-label="输入消息" placeholder={readOnly?'已归档会话仅供查阅，恢复后可继续发送':pending?'可继续讨论，或直接要求制作 Word':inputWaiting?'逐项补充本轮问题，注明资料来源或尚无法确定之处':'描述信披问题、公告、Word 或知识库更新需求；Shift + Enter 换行'} value={text} readOnly={readOnly} onChange={e=>setText(e.target.value)} autoSize={{minRows:2,maxRows:6}} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing&&e.keyCode!==229){e.preventDefault();void send();}}}/>
    <div className="composer-foot"><span>{readOnly?'当前为归档记录，恢复后可继续对话':running?`${runLabels[running.status]} · 可追加当前任务要求`:pending?'可继续讨论或制作 Word；事项确认记录保留':'可直接咨询、拟写公告、制作 Word 或管理知识库'}</span>{running?<><Select aria-label="追加消息时机" value={deliveryMode} onChange={setDeliveryMode} options={[{value:'steer',label:'当前工具结束后追加'},{value:'follow_up',label:'当前工作结束后处理'}]}/><Button disabled={!canSend} loading={busy} onClick={()=>send()}>追加消息</Button><Button icon={<StopOutlined/>} disabled={busy||running.status==='cancelling'} onClick={()=>act(async()=>{const r=await api<PiRun>(`/chat/runs/${running.id}/cancel`,'POST',{});setRuns(prev=>prev.map(x=>x.id===r.id?r:x));})}>停止执行</Button></>:<Button type="primary" icon={<ArrowUpOutlined/>} loading={busy} disabled={!canSend} onClick={()=>send()}>发送消息</Button>}</div>
   </div>}
  </section></div>

 </section>;
}
