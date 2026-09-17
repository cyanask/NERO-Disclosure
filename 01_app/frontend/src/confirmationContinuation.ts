import type {DisclosureEvent} from './types';
import type {PiRun,Receipt} from './chat';
import {live} from './chat';

export interface ConfirmationContinuation {status:string;reason?:string;run_id?:string}
export interface ResumePending {sid:string;eventId:string;parent?:string;runId?:string;approvalId?:string;requestedAt:number}
export function watchConfirmation(continuation:ConfirmationContinuation|undefined,event:DisclosureEvent,sid:string,requestedAt:number):ResumePending|undefined{
 if(!continuation?.run_id||!['accepted','queued'].includes(continuation.status))return;
 return {sid,eventId:event.id,requestedAt,approvalId:[...(event.approval_records||[])].reverse().find(r=>r.state==='current')?.id,
  ...(continuation.status==='queued'?{parent:continuation.run_id}:{runId:continuation.run_id})};
}
export function restoreContinuation(event:DisclosureEvent|undefined,sid:string,runs:PiRun[]):ResumePending|undefined{
 if(!event)return;
 const parent=runs.find(r=>r.session_id===sid&&r.event_id===event.id&&r.resume_after_settle&&event.approval_records?.some(a=>a.id===r.resume_after_settle&&a.state==='current'));
 return parent?{sid,eventId:event.id,parent:parent.id,approvalId:parent.resume_after_settle!,requestedAt:parent.updated}:undefined;
}
export function continuationFailure(continuation?:ConfirmationContinuation){
 return continuation&&['blocked','not_configured'].includes(continuation.status)
  ?continuation.reason||'确认已保存，自动接续未启动，请查看执行记录。':undefined;
}
// Loading a new run is distinct from completing its work. Only bound run IDs or
// the backend's human_resume receipt establish that the continuation appeared.
export function observeContinuation(pending:ResumePending,runs:PiRun[],rows:Receipt[]):{action:'reload'|'waiting'|'failed'|'paused';reason?:string}{
 const scoped=runs.filter(r=>r.session_id===pending.sid&&r.event_id===pending.eventId);
 if(pending.runId&&scoped.some(r=>r.id===pending.runId))return {action:'reload'};
 if(pending.parent&&scoped.some(r=>r.id!==pending.parent&&rows.some(row=>row.run_id===r.id&&row.kind==='human_resume'&&!!pending.approvalId&&row.body.approval_id===pending.approvalId)))return {action:'reload'};
 const parent=scoped.find(r=>r.id===pending.parent);
 if(parent?.resume_cancelled_for===pending.approvalId&&pending.approvalId)return {action:'paused',reason:'已按你的操作暂停自动接续。'};
 if(parent?.continuation_run_id&&parent.resume_confirmation_id===pending.approvalId)return {action:scoped.some(r=>r.id===parent.continuation_run_id)?'reload':'waiting'};
 const paused=rows.some(row=>row.kind==='continuation_paused'&&row.run_id===pending.parent&&row.at>=pending.requestedAt);
 if(paused)return {action:'paused',reason:'已按你的操作暂停自动接续。'};
 const failure=[...rows].reverse().find(row=>row.kind==='continuation_failed'&&row.at>=pending.requestedAt&&scoped.some(r=>r.id===row.run_id));
 if(failure)return {action:'failed',reason:typeof failure.body.reason==='string'?failure.body.reason:'自动接续未启动，请查看执行记录。'};
 if(parent&&['cancelled','interrupted'].includes(parent.status))return {action:'failed',reason:parent.reason||'上一轮已停止，自动接续未启动。'};
 if(parent&&!live(parent)&&!parent.resume_after_settle)return {action:'failed',reason:'确认已保存，后台已不再等待自动接续；未观察到新的运行，请查看执行记录。'};
 return {action:'waiting'};
}
