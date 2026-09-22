import type {PiRun,Receipt} from './chat';
import {nodeLabels,runLabels} from './chat';

export type ActivityState='requested'|'running'|'done'|'failed'|'unknown';
export type WorkActivity={key:string;seq:number;label:string;state:ActivityState;detail:string};
export type WorkProgress={tone:'quiet'|'active'|'human'|'blocked'|'done';title:string;detail:string;animate:boolean;historical:boolean;activities:WorkActivity[];action?:'input'|'knowledge'|'documents'|'review';actionLabel?:string};
const text=(v:unknown)=>typeof v==='string'?v:'';
const object=(v:unknown):Record<string,unknown>=>v&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:{};
const names:Record<string,string>={search_library:'检索资料库',read_library:'读取资料正文',read_event:'读取事项事实',
 knowledge_search:'检索知识库',knowledge_read:'读取知识库条目',knowledge_history:'查阅历史公告',knowledge_web_search:'检索公开来源',knowledge_download:'取得公开资料',knowledge_download_read:'读取公开资料',
 read_document_context:'读取当前文稿与资料',read_document:'读取文稿',read_document_template:'读取文稿模板',read_attachment:'读取补充附件',make_word:'制作 Word',save_announcement:'保存公告正文',
 knowledge_propose:'准备知识库变更',knowledge_import_propose:'准备资料入库预览',knowledge_import_url:'取得待入库资料',knowledge_template_replace:'准备模板替换',knowledge_delete_prepare:'准备删除预览',
 load_business_skill:'加载业务方法',prepare_disclosure_workflow:'开始事项办理',confirm_announcement_text:'登记正文确认',
 request_information:'整理待补问题',submit_candidate:'提交工作结果',lifecycle_submit:'登记法规核验结果',
 'task.library.search':'检索资料库','task.library.read':'读取资料正文','event.get':'读取事项事实','task.evaluate':'核验工作结果','verify.run':'核验工作结果'};
const hidden=new Set(['route_request','task.request','task.open','task.finish','gate.advance']);
const labels:Record<string,string>={drafts_saved:'公告正文版本已保存',documents_created:'Word 文件已登记',documents_reused:'沿用已登记 Word',artifact:'Word 文件已登记',text_confirmed:'正文确认已记录',knowledge_proposal:'知识库变更预览已准备好',knowledge_applied:'知识库变更已执行',questions:'已提出待补问题',verification:'工作结果核验'};

/** Read-only projection of one run. No name-based matching, business writes or inferred future steps. */
export function workActivities(run:PiRun,rows:Receipt[]):WorkActivity[]{
 const own=[...new Map(rows.filter(r=>r.run_id===run.id).map(r=>[r.seq,r])).values()].sort((a,b)=>a.seq-b.seq);
 const canonical=own.some(r=>r.body.transport==='pi_model');
 const items:WorkActivity[]=[],calls=new Map<string,WorkActivity>();
 for(const row of own){
  const b=row.body,name=text(b.name),id=text(b.id),kind=row.kind;
  if(hidden.has(name))continue;
  if(['tool_requested','tool_started','tool_returned','tool_failed'].includes(kind)){
   if(canonical&&b.transport!=='pi_model')continue;
   const key=id?`${text(b.transport)}:${id}`:'';
   const state:ActivityState=kind==='tool_requested'?'requested':kind==='tool_started'?'running':kind==='tool_failed'?'failed':'done';
   const prior=key?calls.get(key):undefined;
   if(prior){prior.state=state;prior.detail=state==='failed'?text(b.error)||'该次处理未完成。':'';continue;}
   const item={key:`receipt-${row.seq}`,seq:row.seq,label:names[name]||'处理请求',state,detail:state==='failed'?text(b.error)||'该次处理未完成。':!id&&state==='done'?'已有返回记录，未关联具体请求。':''};
   items.push(item);if(key)calls.set(key,item);
  }else if(!canonical&&['knowledge_requested','knowledge_returned','script_started','script_returned','script_failed','model_tool_failed'].includes(kind)){
   // Older records may have no correlation ID. Keep each observation independent.
   items.push({key:`receipt-${row.seq}`,seq:row.seq,label:kind.startsWith('script_')?'制作 Word':names[name]||'处理资料',state:kind.endsWith('failed')?'failed':kind.endsWith('returned')?'done':kind==='script_started'?'running':'requested',detail:kind.endsWith('returned')?'返回记录；不推定对应哪次请求。':text(b.error)});
  }else if(labels[kind]){
   const check=kind==='verification';
   const state:ActivityState=check?(b.status==='PASS'?'done':b.status==='BLOCKED'?'failed':'unknown'):'done';
   let detail=check?(b.status==='PASS'?'自动检查通过，不代表人工确认。':b.status==='BLOCKED'?'核验发现待处理问题。':'核验结果尚待确认。'):'';
   if(['documents_created','documents_reused','drafts_saved'].includes(kind))detail=(Array.isArray(b.documents)?b.documents:[]).map(d=>{const v=object(d);return [text(v.title),typeof v.version==='number'?`v${v.version}`:''].filter(Boolean).join(' ');}).filter(Boolean).join('；');
   if(kind==='knowledge_proposal')detail=text(b.summary)||'已准备变更预览，执行状态见后续记录。';
   if(kind==='questions')detail=(Array.isArray(b.questions)?b.questions:[]).filter(q=>typeof q==='string').join('；');
   items.push({key:`receipt-${row.seq}`,seq:row.seq,label:labels[kind],state,detail});
  }
 }
 return items;
}

export function workProgress(run:PiRun|undefined,rows:Receipt[]=[],options:{disconnected?:boolean;historical?:boolean;pendingReview?:string}={}):WorkProgress{
 const historical=!!options.historical;
 const result:WorkProgress={tone:'quiet',title:'尚未开始',detail:'直接说明需求即可，无需选择固定路线。',animate:false,historical,activities:[]};
 if(!run)return result;
 const activities=workActivities(run,rows);result.activities=activities;
 const docs=(run.documents||[]).filter(d=>d.run_id===run.id||d.run_id===undefined&&['document','announcement'].includes(run.stage));
 const own=rows.filter(r=>r.run_id===run.id);
 const textSaved=docs.some(d=>d.format==='text')||own.some(r=>r.kind==='drafts_saved');
 const wordRegistered=docs.some(d=>d.format!=='text')||own.some(r=>['documents_created','documents_reused'].includes(r.kind));
 const legacyArtifact=!!run.artifact_id||own.some(r=>r.kind==='artifact');
 const recorded=wordRegistered||legacyArtifact;
 const documentAction=legacyArtifact&&!wordRegistered?'review' as const:'documents' as const;
 const finished=new Set(['completed','waiting_user','waiting_approval','waiting_knowledge_confirmation','failed','cancelled','interrupted','incomplete','blocked']);
 // Historical, disconnected and terminal views never show an old start as still executing.
 if(historical||options.disconnected||finished.has(run.status)||run.status==='cancelling')result.activities=activities.map(a=>a.state==='running'||a.state==='requested'?{...a,state:'unknown',detail:a.detail||'未收到该次操作的明确完成记录。'}:a);
 if(historical){result.tone=run.status==='completed'?'done':result.tone;result.title=`历史轮次 · ${runLabels[run.status]||'状态未明确'}`;result.detail='这里保留当时的工作与版本记录，不代表当前文稿状态。';return result;}
 if(options.disconnected){result.title='连接中断，状态待同步';result.detail=`最后已知：${nodeLabels[run.stage]||'需求处理'} · ${runLabels[run.status]||'状态未明确'}。已有记录保留，不自动重发请求。`;return result;}
 if(run.status==='accepted'){result.tone='active';result.title='等待启动';result.detail='请求已接收，尚未开始执行。';return result;}
 if(run.status==='cancelling'){result.tone='active';result.title='正在停止';result.detail='停止请求已登记，等待执行结束；已有结果保留。';return result;}
 if(run.status==='waiting_user'){return {...result,tone:'human',title:'需要你补充信息',detail:run.questions?.[0]||run.reason||'请查看本轮待补问题。',action:'input',actionLabel:'去补充'};}
 if(run.status==='waiting_knowledge_confirmation')return {...result,tone:'human',title:'知识库变更待确认',detail:run.knowledge_change?.summary||'已准备变更预览，尚未执行。',action:'knowledge',actionLabel:'查看变更预览'};
 if(run.status==='waiting_approval'){return {...result,tone:'human',title:options.pendingReview?`需要人工${options.pendingReview}`:'需要人工确认',detail:run.reason||'请核对当前对象和版本。',action:'review',actionLabel:'查看待确认事项'};}
 if(['failed','interrupted','incomplete','blocked','cancelled'].includes(run.status))return {...result,tone:run.status==='cancelled'?'quiet':'blocked',title:runLabels[run.status],detail:[run.reason||'请查看本轮记录。',recorded?(documentAction==='review'?'已有文件登记记录，可在事项记录中核对。':'已有文件登记记录，可在文档区核对。'):''].filter(Boolean).join(' '),...(recorded?{action:documentAction,actionLabel:documentAction==='review'?'查看事项文稿':'查看文稿'}:{})};
 if(run.status==='completed'){
  result.tone='done';
  result.title=run.stage==='confirmation'?'正文确认已记录':recorded?'Word 工作稿已生成':textSaved?'公告正文已保存':own.some(r=>r.kind==='knowledge_applied')?'知识库变更已执行':'本轮已完成';
  result.detail=run.stage==='confirmation'?'确认只针对当时指定的正文版本，不代表 Word 文件验收或发布。':recorded?'文件生成与内容审阅分别记录，请核对登记版本和待补项。':textSaved?'正文版本与待补事项保留，可继续修改或要求制作 Word。':'本轮处理已结束，可查看答复及依据。';
  if(['failed','interrupted'].includes(run.finalization_status||''))result.detail+=' 收尾答复未完成，已登记的结果仍保留。';
  if(recorded||textSaved){result.action=documentAction;result.actionLabel=documentAction==='review'?'查看事项文稿':'查看文稿';}
  return result;
 }
 if(run.status==='running'){
  const active=[...activities].reverse().find(a=>a.state==='running');
  result.tone='active';result.animate=true;
  result.title=active?`正在${active.label}`:run.active_phase==='routing'?'正在理解本轮需求':run.finalization_status==='started'?'正在整理答复':run.active_phase==='cleanup'?'正在结束本轮处理':run.stage==='announcement'?'正在组织公告正文':'正在处理请求';
  result.detail=active?'当前操作尚未结束。':'处理中，可随时停止。';
  return result;
 }
 result.title='状态待核对';result.detail='当前记录不足以确认执行结果，请查看已有记录。';return result;
}

// Kept for genuine historical business records, not for routing new conversations.
export const legacyWorkflowStages=['assessment','plan','template','draft','word'];
export function eventRefreshSequence(run:PiRun|undefined,rows:Receipt[]):number{
 if(!run||run.event_id.startsWith('conversation:'))return 0;
 for(const row of [...rows].reverse()){
  if(row.run_id!==run.id)continue;
  if(['verification','result_snapshot','stage_transition','facts_supplemented','artifact'].includes(row.kind))return row.seq;
  if(row.kind==='tool_returned'&&['task.evaluate','event.update','law.bind','task.finish','gate.advance'].includes(text(row.body.name)))return row.seq;
 }
 return 0;
}
