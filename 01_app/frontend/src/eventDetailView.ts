import type {DisclosureEvent,Gate} from './types';
import {pendingHumanGate,supportsConfirmation} from './humanGates';

export const eventStageNames:Record<string,string>={assessment:'披露判断',plan:'披露清单',template:'模板适配',draft:'公告文稿',word:'Word 核验'};
const stageMap:Record<string,string>={intake:'assessment',assessed:'assessment',assessment_verified:'assessment',needs_reassessment:'assessment',accepted:'assessment',awaiting_assessment_information:'assessment',no_disclosure_manual_tracking:'assessment',specialist_handling:'assessment',planning:'plan',planned:'plan',plan_verified:'plan',plan_revision_required:'plan',selecting_template:'template',template_revision_required:'template',drafting:'draft',drafted:'draft',draft_verified:'draft',draft_revision_required:'draft',text_draft_ready:'draft',text_confirmed:'draft',delivered:'word',confirmed_draft_archived:'word'};
export function currentEventStage(event:DisclosureEvent):string{
 const pending=event.stage.match(/^awaiting_(assessment|plan|template|draft|word)_confirmation$/)?.[1];
 const selected=pending||(event.stage==='manual_escalation'?(event.escalation?.node||'assessment'):undefined)||stageMap[event.stage];
 if(selected&&eventStageNames[selected])return event.output_mode==='text'&&['template','word'].includes(selected)?'draft':selected;
 return event.current_artifact_id&&event.output_mode!=='text'?'word':event.draft?'draft':event.template&&event.output_mode!=='text'?'template':event.plan?'plan':'assessment';
}
export function currentStageResult(event:DisclosureEvent,stage:string){
 return stage==='word'?event.artifacts?.find(a=>a.id===event.current_artifact_id):stage==='draft'?event.draft:stage==='template'?event.template:stage==='plan'?event.plan:event.assessment;
}
export function eventDetailState(event:DisclosureEvent,stage:string,gate?:Gate){
 const outdated=!!gate?.issues.some(i=>['method_changed','contract_version_missing'].includes(i.code));
 const lawProblem=!!gate?.issues.some(i=>i.code.startsWith('law_'));
 const confirmed=gate?.status==='PASS'?[...(event.approval_records||[])].reverse().find(r=>r.node===stage&&r.state==='current'&&r.input_fingerprint===gate.input_fingerprint):undefined;
 const active=(event.agent_tasks||[]).filter(t=>t.stage===stage&&['pending','claimed'].includes(t.status));
 const result=currentStageResult(event,stage);
 const candidate=[...(event.agent_tasks||[])].filter(t=>t.stage===stage&&t.result&&t.status==='submitted').sort((a,b)=>b.created_at-a.created_at)[0];
 const confirmationSupported=supportsConfirmation(event,stage);
 const special=stage==='assessment'&&gate?.next_action.action==='manual_escalation';
 const needsConfirmation=confirmationSupported&&gate?.status==='PASS'&&!confirmed&&(pendingHumanGate(event)?.stage===stage||gate.next_action.action==='human_review'||special);
 let title='正在核对当前情况',description='核对完成后显示本阶段可执行的操作。';
 if(active.length){title='有任务待处理';description=active.some(t=>t.status==='claimed')?'任务已被领取，可查看进展或停止任务。':'任务正在等待领取，可查看任务明细。';}
 else if(gate?.status==='BLOCKED'){
  title=outdated?(stage==='assessment'?'需要重新判断':`需要更新${eventStageNames[stage]}`):!result&&candidate?'已有候选，等待检查':!result?'尚未形成可用结果':'需要处理当前问题';
  description=outdated?'原结果使用了旧版方法或提交要求，需要按当前要求重新提交。当前不能确认通过。':!result&&candidate?'本阶段已有候选内容，尚未载入当前事项。请先查看并检查候选结果。':!result?'请先在对话中继续办理，形成结果后再核验。当前不能确认通过。':'当前检查未通过，请查看问题并修订；处理前不能确认通过。';
 }else if(gate?.status==='PENDING_REVIEW'){title='需要专业复核';description='自动检查仍有待复核事项，当前不能确认通过。';}
 else if(confirmed){title='当前版本已确认';description=`${confirmed.reviewer} 已确认本阶段结果；确认仅适用于该版本，不代表正式披露。`;}
 else if(needsConfirmation){title=special?'需要人工专项处理':'等待你审阅当前结果';description=special?'本事项涉及专项或重大分歧，请审阅后决定专项处理或退回修订。':'本阶段检查已通过，请审阅完整内容后再作出处理决定。';}
 else if(gate?.status==='PASS'){title='本阶段检查已通过';description='本阶段无需单独人工确认，可查看已有结果和后续办理记录。';}
 return {outdated,lawProblem,confirmed,active,result,candidate,confirmationSupported,needsConfirmation,title,description,
  canReview:confirmationSupported&&!active.length&&!!gate&&!confirmed&&(needsConfirmation||!!result&&gate.status!=='PASS')};
}
