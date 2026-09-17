import type {DisclosureEvent} from './types';
import type {PiRun} from './chat';

export const humanGates=[
 {stage:'assessment',number:1,label:'判断确认',question:'请审阅披露义务、时点、依据及处理决定。',next:'确认准备披露后进入文件与内容规划；也可以决定人工跟踪、专项处理或退回。'},
 {stage:'plan',number:2,label:'规划确认',question:'请审阅文件清单、必答问题、内容颗粒度与待补资料。',next:'确认后进入模板适配。制稿资料的缺口仍会保留。'},
 {stage:'template',number:3,label:'模板确认',question:'请审阅实际模板、章节承载及内容映射。',next:'确认后进入正文制作和自动核验。'},
 {stage:'word',number:4,label:'Word 确认',question:'请打开当前 Word，核对内容并逐页检查排版。',next:'确认后归档当前未公开稿；不自动发布或报送。'}
] as const;
export const continuousHumanGates=[
 {...humanGates[0],label:'例外处理确认',next:'请决定当前不披露并跟踪、专项处理，或继续准备披露。'},
 {stage:'draft',number:1,label:'正文确认',question:'请审阅本次文件清单及每份文件的完整正文。',next:'确认完整正文后定稿；Word 路线将自动继续制作文件。'},
 {...humanGates[3],number:2,label:'Word 文件验收',question:'请打开当前 Word，核对与已确认正文的一致性，并逐页检查实际排版。'}
] as const;
export function humanGatesForEvent(event?:DisclosureEvent){
 if(!event)return continuousHumanGates.filter(g=>g.stage!=='assessment');
 if(event?.workflow_policy!=='continuous-v1')return humanGates;
 return continuousHumanGates.filter(g=>g.stage==='assessment'
  ?event.stage==='awaiting_assessment_confirmation'||['no_disclosure_manual_tracking','specialist_handling','manual_escalation'].includes(event.stage)||event.approval_records?.some(r=>r.node==='assessment'&&r.state==='current')
  :g.stage!=='word'||event.output_mode!=='text').map(g=>g.stage==='draft'?{...g,next:event.output_mode==='text'?'确认后正文定稿；不制作 Word，不自动发布或报送。':'确认完整正文后自动制作 Word，再由你核对文件与已确认正文的一致性及实际排版。'}:g);
}
export function supportsConfirmation(event:DisclosureEvent,stage:string){return (event.workflow_policy==='continuous-v1'?continuousHumanGates:humanGates).some(g=>g.stage===stage)&&(stage!=='word'||event.output_mode!=='text');}
export function pendingHumanGate(event?:DisclosureEvent){return humanGatesForEvent(event).find(g=>event?.stage===`awaiting_${g.stage}_confirmation`);}
export const independentTask=(run?:PiRun)=>!!run&&['chat','announcement','document','confirmation'].includes(run.stage);
export function canSubmitConfirmation({stage,decision,reviewer,reason,gate,content,visual,hasDraft=true,hasArtifact=true}:{stage:string;decision:string;reviewer:string;reason:string;gate?:{status:string};content:boolean;visual:boolean;hasDraft?:boolean;hasArtifact?:boolean}){
 if(!reviewer.trim()||!reason.trim())return false;
 if(decision==='reject')return true;
 return gate?.status==='PASS'&&(stage!=='draft'||content&&hasDraft)&&(stage!=='word'||content&&visual&&hasArtifact);
}
export function needsUserInput(event?:DisclosureEvent,run?:PiRun){
 if(independentTask(run))return !!event&&run?.event_id===event.id&&run.status==='waiting_user';
 return !!event&&run?.event_id===event.id&&run.status==='waiting_user'&&!pendingHumanGate(event)&&!['text_confirmed','confirmed_draft_archived','no_disclosure_manual_tracking','specialist_handling','manual_escalation'].includes(event.stage);
}

export function wordReviewCopy(event:DisclosureEvent){
 return {content:event.workflow_policy==='continuous-v1'?'我已核对当前 Word 与已确认正文一致，无遗漏或意外改动':'我已核对当前 Word 的内容、数据、程序及适用限制',
  visual:'我已打开当前 Word 并逐页检查实际排版'};
}
